#!/usr/bin/env bash

# Drive the UR5+RG2 robot through the validated rigid-motion manipulation path.
# The resulting pose log is paired with the Panda log to define the current
# rigid dynamic scope used by the Gazebo-to-Sionna prototype pipeline.

set -e

# Helper for publishing one joint-position command to Gazebo.
u () { gz topic -t /model/ur5_rg2/joint/$1/0/cmd_pos -m gz.msgs.Double -p "data: $2"; }
# The helper is intentionally repeated at stage boundaries so each motion block
# can be read independently without changing the historical script structure.
# Pose for lifting the first item:
u () { gz topic -t /model/ur5_rg2/joint/$1/0/cmd_pos -m gz.msgs.Double -p "data: $2"; }

# 0) fingers slightly open / prepared
u rg2_finger_joint1 0.10
u rg2_finger_joint2 0.10
sleep 0.8

# 1) first turn right and retract slightly
u shoulder_pan_joint 0.45
u shoulder_lift_joint 0
u elbow_joint 0
u wrist_1_joint 0.30
u wrist_2_joint 0.30
u wrist_3_joint 0.35
sleep 1

# 2) turn more and descend
u shoulder_pan_joint 0.90
u shoulder_lift_joint -0.15
u elbow_joint -0.60

u wrist_2_joint 1.61
u wrist_3_joint 1.58
sleep 1

# 3) pre-grasp / almost above the target
u shoulder_pan_joint 1.54
u shoulder_lift_joint -0.42
u elbow_joint -1.05
u rg2_finger_joint1 0.46
u rg2_finger_joint2 0.30
sleep 1

# 4) final pose
u shoulder_pan_joint 1.54
u shoulder_lift_joint -0.55
u elbow_joint -1.38

# Pose for placing the first item.
u () { gz topic -t /model/ur5_rg2/joint/$1/0/cmd_pos -m gz.msgs.Double -p "data: $2"; }

# 0) keep the gripper holding
u rg2_finger_joint1 0.46
u rg2_finger_joint2 0.30
sleep 0.8

# 1) first slight lift, without a large rotation
u shoulder_pan_joint 1.70
u shoulder_lift_joint -0.30
u elbow_joint -1.38
u wrist_1_joint 0.34
u wrist_2_joint 1.60
u wrist_3_joint 1.58
sleep 1

# 2) lift more and rotate
u shoulder_pan_joint 2.00
u shoulder_lift_joint -0.08
u elbow_joint -1.39
u wrist_1_joint 0.36
u wrist_2_joint 1.60
u wrist_3_joint 1.58
sleep 1

# 3) almost final
u shoulder_pan_joint 2.30
u shoulder_lift_joint 0.10
u elbow_joint -1.39
u wrist_1_joint 0.38
u wrist_2_joint 1.59
u wrist_3_joint 1.58
sleep 1

# 4) final
u shoulder_pan_joint 2.58
u shoulder_lift_joint 0.26
u elbow_joint -1.39
u wrist_1_joint 0.39
u wrist_2_joint 1.59
u wrist_3_joint 1.58
u rg2_finger_joint1 0.46
u rg2_finger_joint2 0.29

# Continue the first placement arc toward the right-hand destination before
# returning the arm to its nominal home pose.
u () { gz topic -t /model/ur5_rg2/joint/$1/0/cmd_pos -m gz.msgs.Double -p "data: $2"; }

# 0) keep the gripper holding
u rg2_finger_joint1 0.46
u rg2_finger_joint2 0.29

# 1) slight lift before the large turn
u shoulder_pan_joint 3.10
u shoulder_lift_joint 0.10
u elbow_joint -1.35
u wrist_1_joint 0.39
u wrist_2_joint 1.59
u wrist_3_joint 1.58

# 2) turn more, starting a smooth descent
u shoulder_pan_joint 3.70
u shoulder_lift_joint -0.08
u elbow_joint -1.37
u wrist_1_joint 0.39
u wrist_2_joint 1.59
u wrist_3_joint 1.58

# 3) almost final
u shoulder_pan_joint 4.10
u shoulder_lift_joint -0.30
u elbow_joint -1.39
u wrist_1_joint 0.40
u wrist_2_joint 1.59
u wrist_3_joint 1.58

# 4) final
u shoulder_pan_joint 4.38
u shoulder_lift_joint -0.54
u elbow_joint -1.40
u wrist_1_joint 0.40
u wrist_2_joint 1.59
u wrist_3_joint 1.58
u rg2_finger_joint1 0.25
u rg2_finger_joint2 0.25

# Return to the initial pose so the next scripted pickup starts from a known
# configuration instead of depending on the previous placement endpoint.
u () { gz topic -t /model/ur5_rg2/joint/$1/0/cmd_pos -m gz.msgs.Double -p "data: $2"; }

u shoulder_pan_joint 0.03
u shoulder_lift_joint 0.00
u elbow_joint -0.03
u wrist_1_joint 0.05
u wrist_2_joint -0.04
u wrist_3_joint 0.00
u rg2_finger_joint1 0.06
u rg2_finger_joint2 0.07

# Pose for lifting the second item.
u () { gz topic -t /model/ur5_rg2/joint/$1/0/cmd_pos -m gz.msgs.Double -p "data: $2"; }

# 1) early turn + open the gripper
u shoulder_pan_joint 0.30
u shoulder_lift_joint 0.00
u elbow_joint -0.15
u wrist_1_joint 0.08
u wrist_2_joint 0.55
u wrist_3_joint 0.00
u rg2_finger_joint1 0.28
u rg2_finger_joint2 0.30
sleep 1

# 2) more orientation, still without a large descent
u shoulder_pan_joint 0.58
u shoulder_lift_joint -0.08
u elbow_joint -0.65
u wrist_1_joint 0.12
u wrist_2_joint 1.10
u wrist_3_joint 0.00
u rg2_finger_joint1 0.48
u rg2_finger_joint2 0.50
sleep 1

# 3) pre-grasp
u shoulder_pan_joint 0.93
u shoulder_lift_joint -0.15
u elbow_joint -1.20
u wrist_1_joint 0.16
u wrist_2_joint 1.42
u wrist_3_joint 0.00
u rg2_finger_joint1 0.60
u rg2_finger_joint2 0.62
sleep 1

# 4) almost final
u shoulder_pan_joint 0.93
u shoulder_lift_joint -0.19
u elbow_joint -1.55
u wrist_1_joint 0.18
u wrist_2_joint 1.50
u wrist_3_joint 0.00
u rg2_finger_joint1 0.62
u rg2_finger_joint2 0.65
sleep 1

# 5) final
u shoulder_pan_joint 0.93
u shoulder_lift_joint -0.21
u elbow_joint -1.71
u wrist_1_joint 0.19
u wrist_2_joint 1.56
u wrist_3_joint 0.00
u rg2_finger_joint1 0.64
u rg2_finger_joint2 0.67
sleep 1

# Pose for placing the second item.
u () { gz topic -t /model/ur5_rg2/joint/$1/0/cmd_pos -m gz.msgs.Double -p "data: $2"; }
u shoulder_lift_joint 0.3
sleep 0.5
u shoulder_pan_joint 2.36
sleep 0.5
u shoulder_pan_joint 2.37
u shoulder_lift_joint -0.17
u elbow_joint -1.65
u wrist_1_joint 0.44
u wrist_2_joint 1.56
u wrist_3_joint 0

# Return to the initial pose after the second placement sequence.
u () { gz topic -t /model/ur5_rg2/joint/$1/0/cmd_pos -m gz.msgs.Double -p "data: $2"; }

u shoulder_pan_joint 0.03
u shoulder_lift_joint 0.00
u elbow_joint -0.03
u wrist_1_joint 0.05
u wrist_2_joint -0.04
u wrist_3_joint 0.00
u rg2_finger_joint1 0.06
u rg2_finger_joint2 0.07

# Pose for lifting the third item
u () { gz topic -t /model/ur5_rg2/joint/$1/0/cmd_pos -m gz.msgs.Double -p "data: $2"; }

u rg2_finger_joint1 0.95
u rg2_finger_joint2 1.02
u wrist_1_joint 0.17
u wrist_2_joint 1.60
u wrist_3_joint 1.34
sleep 2
u shoulder_pan_joint -0.15
u shoulder_lift_joint -0.45
u elbow_joint -1.45
sleep 1
# Pose for moving the third item
u () { gz topic -t /model/ur5_rg2/joint/$1/0/cmd_pos -m gz.msgs.Double -p "data: $2"; }
u shoulder_lift_joint 0.15
u shoulder_pan_joint -1.81
sleep 1
u shoulder_lift_joint -0.31
u wrist_1_joint 0.60
u elbow_joint -1.74

# Return to the initial pose:
u () { gz topic -t /model/ur5_rg2/joint/$1/0/cmd_pos -m gz.msgs.Double -p "data: $2"; }

u shoulder_pan_joint 0.03
u shoulder_lift_joint 0.00
u elbow_joint -0.03
u wrist_1_joint 0.05
u wrist_2_joint -0.04
u wrist_3_joint 0.00
u rg2_finger_joint1 0.06
u rg2_finger_joint2 0.07

# Pose for lifting the fourth item
u () { gz topic -t /model/ur5_rg2/joint/$1/0/cmd_pos -m gz.msgs.Double -p "data: $2"; }

u wrist_1_joint 0.53
u wrist_2_joint 1.60
u wrist_3_joint 0.00
u rg2_finger_joint1 0.48
u rg2_finger_joint2 0.48
sleep 1
u elbow_joint -1.18
u shoulder_pan_joint -0.68
u shoulder_lift_joint -0.71
sleep 1

# Pose for moving the fourth item
u () { gz topic -t /model/ur5_rg2/joint/$1/0/cmd_pos -m gz.msgs.Double -p "data: $2"; }
u shoulder_lift_joint 0
sleep 1
u shoulder_pan_joint -3.83
sleep 1
u wrist_1_joint 0.67
sleep 1
u elbow_joint -2.19

# Return to the initial pose:
u () { gz topic -t /model/ur5_rg2/joint/$1/0/cmd_pos -m gz.msgs.Double -p "data: $2"; }

u shoulder_pan_joint 0.03
u shoulder_lift_joint 0.00
u elbow_joint -0.03
u wrist_1_joint 0.05
u wrist_2_joint -0.04
u wrist_3_joint 0.00
u rg2_finger_joint1 0.06
u rg2_finger_joint2 0.07
