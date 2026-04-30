#!/usr/bin/env bash

# Drive the Panda robot through the validated rigid-motion pickup/place program.
# The exact joint command sequence is part of the prototype motion dataset used
# by the current rigid Panda/UR5 dynamic pipeline.

set -e

# Helper for publishing one joint-position command to Gazebo.
p () { gz topic -t /model/Panda/joint/$1/0/cmd_pos -m gz.msgs.Double -p "data: $2"; }
# The helper is intentionally redefined at stage boundaries in this script so
# each motion block can be read in isolation while preserving the old workflow.
# Pose for grasping the first item:
p () { gz topic -t /model/Panda/joint/$1/0/cmd_pos -m gz.msgs.Double -p "data: $2"; }

p panda_joint1 -0.65
p panda_joint3 -0.03
p panda_joint4 -0.06
p panda_joint5 0.05
p panda_joint6 1.90
p panda_joint7 -0.52
p panda_finger_joint1 0.04
p panda_finger_joint2 0.04
sleep 3.0

p panda_joint2 1.58

# Pose for placing the first item. The comments below describe task-space intent
# rather than low-level kinematics so the motion story remains readable.
p () { gz topic -t /model/Panda/joint/$1/0/cmd_pos -m gz.msgs.Double -p "data: $2"; }

# 0) hold the part
p panda_finger_joint1 0.02
p panda_finger_joint2 0.02
sleep 0.8

# 1) raise high
p panda_joint1 -0.40
p panda_joint2 0.55
p panda_joint3 0.20
p panda_joint4 -1.10
p panda_joint5 0.00
p panda_joint6 1.65
p panda_joint7 -0.65
sleep 1

# 2) move high
p panda_joint1 0.45
p panda_joint2 0.50
p panda_joint3 0.55
p panda_joint4 -1.25
p panda_joint5 -0.35
p panda_joint6 1.75
p panda_joint7 -0.95

# 3) pre-place, still high
p panda_joint1 0.95
p panda_joint2 0.50
p panda_joint3 0.78
p panda_joint4 -1.00
p panda_joint5 -0.80
p panda_joint6 1.88
p panda_joint7 -1.30

# 4) one more intermediate turn toward the new final pose
p panda_joint1 1.15
p panda_joint2 0.50
p panda_joint3 0.86
p panda_joint4 -0.90
p panda_joint5 -0.95
p panda_joint6 1.92
p panda_joint7 -1.40

# 5) lower to the final pose
p panda_joint1 1.30
p panda_joint3 0.93
p panda_joint4 -0.71
p panda_joint5 -1.05
p panda_joint6 1.94
p panda_joint7 -1.49

# 6) joint2 last
p panda_joint2 1.33

# 7) release
p panda_finger_joint1 0.03
p panda_finger_joint2 0.03

# Pose for grasping the second item.
p () { gz topic -t /model/Panda/joint/$1/0/cmd_pos -m gz.msgs.Double -p "data: $2"; }

# 0) if the hand is empty, keep the fingers open
p panda_finger_joint1 0.03
p panda_finger_joint2 0.03
sleep 0.8

# 1) retract and raise so it does not move low over the table
p panda_joint1 1.05
p panda_joint2 0.70
p panda_joint3 0.45
p panda_joint4 -1.15
p panda_joint5 -0.95
p panda_joint6 1.95
p panda_joint7 -1.20
sleep 1

# 2) high turn toward the central zone
p panda_joint1 0.55
p panda_joint2 0.72
p panda_joint3 0.35
p panda_joint4 -1.10
p panda_joint5 -0.80
p panda_joint6 1.85
p panda_joint7 -0.40
sleep 1

# 3) high move toward the target
p panda_joint1 0.05
p panda_joint2 0.78
p panda_joint3 0.30
p panda_joint4 -0.95
p panda_joint5 -0.65
p panda_joint6 1.72
p panda_joint7 0.15
p panda_finger_joint1 0.04
p panda_finger_joint2 0.04
sleep 1

# 4) pre-place, still slightly above the final pose
p panda_joint1 -0.12
p panda_joint2 0.95
p panda_joint3 0.27
p panda_joint4 -0.78
p panda_joint5 -0.55
p panda_joint6 1.62
p panda_joint7 0.45
sleep 1

# 5) lower to the final pose
p panda_joint1 -0.21
p panda_joint3 0.25
p panda_joint4 -0.53
p panda_joint5 -0.46
p panda_joint6 1.55
p panda_joint7 0.69
sleep 1

# 6) joint2 last
p panda_joint2 1.28
sleep 1

# Pose for placing the second item.
p () { gz topic -t /model/Panda/joint/$1/0/cmd_pos -m gz.msgs.Double -p "data: $2"; }

# 0) keep the fingers slightly open
p panda_finger_joint1 0.03
p panda_finger_joint2 0.03
sleep 0.8

# 1) raise higher from the current pose
p panda_joint1 -0.35
p panda_joint2 0.58
p panda_joint3 0.18
p panda_joint4 -1.35
p panda_joint5 -0.48
p panda_joint6 2.20
p panda_joint7 0.68
sleep 1

# 2) high turn to the left
p panda_joint1 -0.95
p panda_joint2 0.54
p panda_joint3 0.22
p panda_joint4 -1.48
p panda_joint5 -0.48
p panda_joint6 2.24
p panda_joint7 0.68
sleep 1

# 3) high move above the target area
p panda_joint1 -1.32
p panda_joint2 0.52
p panda_joint3 0.28
p panda_joint4 -1.58
p panda_joint5 -0.48
p panda_joint6 2.25
p panda_joint7 0.68
sleep 1

# 4) still high, almost above the final pose
p panda_joint1 -1.48
p panda_joint2 0.56
p panda_joint3 0.36
p panda_joint4 -1.63
p panda_joint5 -0.48
p panda_joint6 2.20
p panda_joint7 0.68
sleep 1

# 5) lower down toward the final pose
p panda_joint1 -1.56
p panda_joint2 0.66
p panda_joint3 0.46
p panda_joint4 -1.62
p panda_joint5 -0.48
p panda_joint6 2.12
p panda_joint7 0.68
sleep 1

# 6) final pose
p panda_joint3 0.54
p panda_joint6 2.08
sleep 1

# 7) joint2 last
p panda_joint2 0.76
sleep 1

# Pose for grasping the third item.
p () { gz topic -t /model/Panda/joint/$1/0/cmd_pos -m gz.msgs.Double -p "data: $2"; }

# 0) fingers
p panda_finger_joint1 0.03
p panda_finger_joint2 0.03
sleep 0.8

# 1) very high initial retraction
p panda_joint1 -1.30
p panda_joint2 0.36
p panda_joint3 0.10
p panda_joint4 -2.00
p panda_joint5 -0.22
p panda_joint6 2.42
p panda_joint7 0.82
sleep 1

# 2) high move toward the center, still without descending
p panda_joint1 -0.72
p panda_joint2 0.40
p panda_joint3 0.09
p panda_joint4 -1.86
p panda_joint5 -0.16
p panda_joint6 2.34
p panda_joint7 1.00
sleep 1

# 3) still high, moving toward the right side
p panda_joint1 -0.12
p panda_joint2 0.40
p panda_joint3 0.08
p panda_joint4 -1.58
p panda_joint5 -0.11
p panda_joint6 2.16
p panda_joint7 1.18
sleep 1

# 4) above the target area, but still high
p panda_joint1 0.30
p panda_joint2 0.40
p panda_joint3 0.06
p panda_joint4 -1.20
p panda_joint5 -0.08
p panda_joint6 1.94
p panda_joint7 1.32
sleep 1

# 5) begin a smooth descent
p panda_joint1 0.56
p panda_joint2 0.70
p panda_joint3 0.04
p panda_joint4 -0.86
p panda_joint5 -0.06
p panda_joint6 1.76
p panda_joint7 1.40
sleep 1

# 6) a little lower, but not all the way
p panda_joint1 0.70
p panda_joint2 0.98


# Pose for placing the third item:
p () { gz topic -t /model/Panda/joint/$1/0/cmd_pos -m gz.msgs.Double -p "data: $2"; }

# 0) fingers
p panda_finger_joint1 0.03
p panda_finger_joint2 0.03

# 1) first retract and raise, without starting low
p panda_joint1 0.68
p panda_joint2 0.62
p panda_joint3 0.08
p panda_joint4 -1.45
p panda_joint5 -0.12
p panda_joint6 2.15
p panda_joint7 1.30

# 2) high move toward the center
p panda_joint1 0.35
p panda_joint2 0.54
p panda_joint3 0.12
p panda_joint4 -1.32
p panda_joint5 -0.16
p panda_joint6 2.10
p panda_joint7 1.22

# 3) a little more to the left, still high
p panda_joint1 0.08
p panda_joint2 0.54
p panda_joint3 0.16
p panda_joint4 -1.15
p panda_joint5 -0.21
p panda_joint6 2.04
p panda_joint7 1.14

# 4) begin a smooth descent toward the final pose
p panda_joint1 -0.05
p panda_joint2 0.54
p panda_joint3 0.19
p panda_joint4 -0.98
p panda_joint5 -0.25
p panda_joint6 1.99
p panda_joint7 1.08
 
# 5) final
p panda_joint1 -0.13
p panda_joint2 0.51
p panda_joint3 0.21
p panda_joint4 -0.83
p panda_joint5 -0.27
p panda_joint6 1.96
p panda_joint7 1.05
p () { gz topic -t /model/Panda/joint/$1/0/cmd_pos -m gz.msgs.Double -p "data: $2"; }

# 0) fingers
p panda_finger_joint1 0.03
p panda_finger_joint2 0.03

# 1) raise and fold in place
p panda_joint1 -0.15
p panda_joint2 0.48
p panda_joint3 0.30
p panda_joint4 -0.83
p panda_joint5 -0.20
p panda_joint6 2.12
p panda_joint7 0.98

# 2) retract further, still high
p panda_joint1 -0.40
p panda_joint2 0.46
p panda_joint3 0.40
p panda_joint4 -0.83
p panda_joint5 -0.14
p panda_joint6 2.22
p panda_joint7 0.90

# 3) sweep left without dropping
p panda_joint1 -0.95
p panda_joint2 0.45
p panda_joint3 0.48
p panda_joint4 -0.83
p panda_joint5 -0.09
p panda_joint6 2.28
p panda_joint7 0.82

# 4) almost final
p panda_joint1 -1.50
p panda_joint2 0.44
p panda_joint3 0.53
p panda_joint4 -0.83
p panda_joint5 -0.06
p panda_joint6 2.30
p panda_joint7 0.74

# 5) final
p panda_joint1 -1.92
p panda_joint2 0.44
p panda_joint3 0.55
p panda_joint4 -2.03
p panda_joint5 -0.05
p panda_joint6 2.29
p panda_joint7 0.70


# Return to the initial pose
p () { gz topic -t /model/Panda/joint/$1/0/cmd_pos -m gz.msgs.Double -p "data: $2"; }

p panda_joint1 -0.23
p panda_joint2 0.00
p panda_joint3 0.11
p panda_joint4 -0.06
p panda_joint5 -0.01
p panda_joint6 0.00
p panda_joint7 0.00
p panda_finger_joint1 0.00
p panda_finger_joint2 0.00
