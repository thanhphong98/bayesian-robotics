#!/usr/bin/env python

import rospy, math, random
import numpy as np
from sensor_msgs.msg import LaserScan
#from laser_geometry import LaserProjection

from mbz_c3_jackal.msg import PositionPolar, Vector
from visualization_msgs.msg import Marker

from kalman_filter import KalmanFilter, Gaussian

class Lidar:
    def __init__(self, scan_topic="/scan"):
        self.bearing = 0.0
        self.bearing_offset = 0.2

        self.scan_sub = rospy.Subscriber(scan_topic, LaserScan, self.on_scan)
        self.cam_pos_sub = rospy.Subscriber("target/cam_position",PositionPolar, self.on_cam_pos)
        self.marker_pub = rospy.Publisher("target/lidar_marker",Marker, queue_size=32)
        self.out_pub = rospy.Publisher("target/lidar_position",PositionPolar, queue_size=32)
        self.scan_pub = rospy.Publisher("/scan/filtered", LaserScan, queue_size=10)
        
    def on_cam_pos(self, msg):
        # rospy.loginfo("Got cam_position")

        self.bearing = math.radians(msg.heading)
        #self.bearing_offset = msg.distance/10


    def on_scan(self, scan):
        # rospy.loginfo("Got scan")

        scan_filtered = self.GetScanInRange(scan, self.bearing-self.bearing_offset, self.bearing+self.bearing_offset)
        self.scan_pub.publish(scan_filtered)

        ## Similar to median, but get the 30% closest point rather than the 50%
        dist = np.percentile(scan_filtered.ranges, 30)

        out_msg = PositionPolar()
        out_msg.distance = dist
        out_msg.heading = math.degrees(self.bearing)
        out_msg.cov_size = 4
        # out_msg.covariance = np.array([
        #     [0.2, 0],   \
        #     [0, 9999],   \
        # ]).flatten().tolist()

        out_msg.covariance = np.array([
            [1e-2, 0, 0, 0],   \
            [0, 1e-1, 0, 0],   \
            [0, 0, 1e-3, 0],   \
            [0, 0, 0, 2e-2],   \
        ]).flatten().tolist()

        self.out_pub.publish(out_msg)
        

    def GetScanInRange(self, scan, angle_min, angle_max):
        scan_filtered = LaserScan()
        scan_filtered.header = scan.header
        scan_filtered.angle_increment = scan.angle_increment
        scan_filtered.range_max = scan.range_max
        scan_filtered.range_min = scan.range_min
        scan_filtered.scan_time = scan.scan_time
        scan_filtered.time_increment = scan.time_increment
        
        ## Round the input range to the closest valid angle
        num_pts = len(scan.ranges)-1

        min_idx = int(round((angle_min-scan.angle_min)/scan.angle_increment))
        if min_idx < 0:
            print("Warning: angle_min is less than minimum scan angle.")
            min_idx = 0
        elif min_idx > num_pts:
            print("Warning: angle_min is less than maximum scan angle.")
            min_idx = num_pts
        angle_min = scan.angle_min + min_idx*scan.angle_increment

        max_idx = int(round((angle_max-scan.angle_min)/scan.angle_increment))
        if max_idx < 0:
            print("Warning: angle_max is less than minimum scan angle.")
            max_idx = 0
        elif max_idx > num_pts:
            print("Warning: angle_max is less than maximum scan angle.")
            max_idx = num_pts
        angle_max = scan.angle_min + max_idx*scan.angle_increment
        
        ## Output the final values
        scan_filtered.angle_min = angle_min
        scan_filtered.angle_max = angle_max
        scan_filtered.ranges = scan.ranges[min_idx:max_idx]

        """
        for i in range(len(scan.ranges)):
            angle = angle_min + angle_inc*i
            angle_deg = math.degrees(angle)
            print("Angle: {:3.2f} deg, Range: {:2.2f}".format(angle_deg, scan.ranges[i]))
        """
        return scan_filtered

class LidarTracker(KalmanFilter):
    
    def __init__(self, _dist, _theta):
        self.A = np.array([  \
            [1, 0, 1, 0], \
            [0, 1, 0, 1], \
            [0, 0, 1, 0], \
            [0, 0, 0, 1], \
        ])

        self.C = np.array([  \
            [1, 0, 0, 0],   \
            [0, 1, 0, 0],   \
            [0, 0, 1, 0],   \
            [0, 0, 0, 1],   \
        ])

        self.B = np.array([0])
        self.D = np.array([0])

        self.w = Gaussian.diagonal( [0, 0, 0, 0], [1e-1, 1e-4, 1e-1, 1e-4] )
        self.v = Gaussian.diagonal( [0, 0, 0, 0], [1e-2, 2e-1, 5e-1, 1e-2] )

        self.x = Gaussian.diagonal( [_dist, _theta, 0, 0], [1e0, 1e0, 1e0, 1e0] )

        self.yold = [_dist, _theta]

        self.mahalonobis_threshold = 1.0

    def correct(self, y):

        innov_var = np.linalg.inv( self.v.var + np.dot(self.C, np.dot( self.x.var, self.C.T )) )

        match_y = 0
        match_innov_mu = 0
        match_mahalonobis_dist = np.inf
        for ty in y:
            t_innov_mu = ty - np.dot(self.C, self.x.mu)
            t_mahalonobis_dist = np.dot(t_innov_mu, np.dot(innov_var, t_innov_mu ) )

            if( t_mahalonobis_dist < match_mahalonobis_dist ):
                match_mahalonobis_dist = t_mahalonobis_dist
                match_innov_mu = t_innov_mu
                match_y = ty

        y_app = np.append(match_y, [ y[ix]-self.yold[ix] for ix in range(len(y)) ] )

        self.K = np.dot( self.x.var, np.dot( self.C.T, innov_var ) )

        self.x.mu = self.x.mu + np.dot( self.K, match_innov_mu )
        self.x.var = self.x.var - np.dot( self.K, np.dot( self.C, self.x.var ) )

        self.yold = y

if __name__=="__main__":
    rospy.init_node("lidar_detection", anonymous=True)

    Lidar()
    rospy.spin()