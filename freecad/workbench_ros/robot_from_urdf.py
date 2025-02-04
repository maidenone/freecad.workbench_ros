# Generates a ROS::Robot from a URDF robot.

from __future__ import annotations

from math import degrees
from typing import Any, Iterable, Tuple

import FreeCAD as fc

try:
    from urdf_parser_py.urdf import Collision as UrdfCollision
    from urdf_parser_py.urdf import Joint as UrdfJoint
    from urdf_parser_py.urdf import Link as UrdfLink
    from urdf_parser_py.urdf import Robot as UrdfRobot
    from urdf_parser_py.urdf import Visual as UrdfVisual

    from .urdf_parser_utils import axis_to_z
    from .urdf_parser_utils import obj_from_geometry
    from .urdf_parser_utils import placement_along_z_from_joint
    from .urdf_parser_utils import placement_from_origin
except ModuleNotFoundError:
    UrdfCollision = Any
    UrdfJoint = Any
    UrdfLink = Any
    UrdfRobot = Any
    UrdfVisual = Any

from .freecad_utils import add_object
from .freecad_utils import make_group
from .freecad_utils import warn
from .joint import make_joint
from .link import make_link
from .robot import make_robot
from .wb_utils import get_joints

# Typing hints.
DO = fc.DocumentObject
DOList = Iterable[DO]
DOG = fc.DocumentObjectGroup
AppLink = DO  # TypeId == 'App::Link'
AppPart = DO  # TypeId == 'App::Part'
RosLink = DO  # A Ros::Link, i.e. a DocumentObject with Proxy "Link".
RosJoint = DO  # A Ros::Joint, i.e. a DocumentObject with Proxy "Joint".
RosRobot = DO  # A Ros::Robot, i.e. a DocumentObject with Proxy "Robot".
# List of UrdfVisual or List of UrdfCollision.
VisualList = Iterable[UrdfVisual]
CollisionList = Iterable[UrdfCollision]


def robot_from_urdf(
        doc: fc.Document,
        urdf_robot: UrdfRobot,
        ) -> RosRobot:
    """Creates a ROS::Robot from URDF."""

    robot, parts_group = _make_robot(doc, urdf_robot.name)
    # visual_map: dict[str, AppPart] = {}
    # collision_map: dict[str, AppPart] = {}
    for urdf_link in urdf_robot.links:
        ros_link, visual_part, collision_part = _add_ros_link(
            urdf_link, robot, parts_group)
        # visual_map[urdf_link.name] = visual_part
        # collision_map[urdf_link.name] = collision_part
        _add_visual(urdf_link, parts_group, ros_link, visual_part)
        _add_collision(urdf_link, parts_group, ros_link, collision_part)
    joint_map: dict[str, RosJoint] = {}
    for urdf_joint in urdf_robot.joints:
        ros_joint = _add_ros_joint(urdf_joint, robot)
        joint_map[urdf_joint.name] = ros_joint
    # Mimic joints must be handled after creating all joints because the
    # mimicking joint can be defined before the mimicked joint in URDF.
    _define_mimic_joints(urdf_robot, joint_map)
    _compensate_joint_placement(robot, urdf_robot, joint_map)
    return robot


def _make_robot(
        doc: fc.Document,
        name: str = 'robot',
        ) -> tuple[RosRobot, DOG]:
    """Create a ROS::Robot

    Return (robot object, parts group).

    The group called 'Parts' is potentially created and returned. If the object
    'Parts' is not a group, a different name will be given.

    """

    robot = make_robot(name, doc)
    robot.ViewObject.ShowReal = False
    robot.ViewObject.ShowVisual = True
    robot.ViewObject.ShowCollision = False
    # Create a group 'Parts' to hold all parts in the assembly document.
    parts_group = make_group(doc, 'URDF Parts', visible=False)

    return robot, parts_group


def _add_ros_link(
        urdf_link: UrdfLink,
        robot: RosRobot,
        parts_group: DOG,
        ) -> Tuple[RosLink, AppPart, AppPart]:
    """Add two App::Part to the group and links to them to the robot.

    - Add an "App::Part" for the visual of each link.
    - Add an "App::Part for the collision of each link.
    - Add a "Ros::Link" with references to them.

    Return ???.

    Parameters
    ----------
    - robot: robot to add the Ros::Link to.
    - part_groups: group for geometries and "App::Part" objects.
    - name: name of the link if the URDF description.

    """
    name = urdf_link.name
    doc = robot.Document
    visual_part = add_object(parts_group, 'App::Part', f'visual_{name}_')
    visual_part.Visibility = False
    collision_part = add_object(parts_group, 'App::Part', f'collision_{name}_')
    collision_part.Visibility = False
    ros_link = make_link(name, doc)
    ros_link.Label2 = name
    ros_link.adjustRelativeLinks(robot)
    robot.addObject(ros_link)
    # Implementation note: ros_link.Visual.append() doesn't work because ros_link.Visual
    # is a new object on each evoking.
    link_to_visual_part = add_object(parts_group, 'App::Link',
                                     f'visual_{name}')
    # TODO: make a function utils.make_link.
    link_to_visual_part.setLink(visual_part)
    link_to_visual_part.Visibility = False
    ros_link.Visual = [link_to_visual_part]

    link_to_collision_part = add_object(parts_group, 'App::Link',
                                        f'collision_{name}')
    link_to_collision_part.setLink(collision_part)
    link_to_collision_part.Visibility = False
    ros_link.Collision = [link_to_collision_part]
    return ros_link, visual_part, collision_part


def _add_ros_joint(
        urdf_joint: UrdfJoint,
        robot: RosRobot,
        ) -> RosJoint:
    doc = robot.Document
    ros_joint = make_joint(urdf_joint.name, doc)
    ros_joint.Label2 = urdf_joint.name
    ros_joint.adjustRelativeLinks(robot)
    robot.addObject(ros_joint)
    ros_joint.Parent = urdf_joint.parent
    ros_joint.Child = urdf_joint.child
    ros_joint.Type = urdf_joint.type
    ros_joint.Origin = placement_along_z_from_joint(urdf_joint)
    return ros_joint


def _define_mimic_joints(
        urdf_robot: UrdfRobot,
        joint_map: dict[str, RosJoint],
        ) -> None:
    """Add the correct properties for mimic joints."""
    for name, ros_joint in joint_map.items():
        urdf_joint = urdf_robot.joint_map[name]
        if urdf_joint.mimic is None:
            continue
        if urdf_joint.type not in ['prismatic', 'revolute', 'continuous']:
            warn(f'Mimicking joint "{urdf_joint.name}" has type '
                 f'{urdf_joint.type} but only prismatic, revolute,'
                 ' and continuous types are supported, ignoring "mimic"', True)
            continue
        ros_joint.Mimic = True
        mimicked_urdf_joint = urdf_robot.joint_map.get(urdf_joint.mimic.joint)
        if not mimicked_urdf_joint:
            warn(f'Joint "{urdf_joint.name}" mimicks the unknown'
                 f' joint "{mimicked_urdf_joint}", ignoring', True)
            continue
        mimicked_ros_joint = joint_map.get(mimicked_urdf_joint.name)
        # `mimicked_ros_joint` should not be None.
        ros_joint.MimickedJoint = mimicked_ros_joint
        ros_joint.Multiplier = urdf_joint.mimic.multiplier
        if urdf_joint.type == 'prismatic':
            # Meters (URDF) to millimeters (FreeCAD).
            offset = urdf_joint.mimic.offset * 1000.0
        else:
            # urdf_joint.type in ['revolute', 'continuous']
            # Radians (URDF) to degrees (FreeCAD).
            offset = degrees(urdf_joint.mimic.offset)
        ros_joint.Offset = offset


def _compensate_joint_placement(
        robot: RosRobot,
        urdf_robot: UrdfRobot,
        joint_map: dict[str, RosJoint],
        ) -> None:
    """Make all joints about/around the z axis."""
    chains = robot.Proxy.get_chains()
    already_compensated_joints: set[RosJoint] = set()
    for chain in chains:
        ros_joints = get_joints(chain)
        previous_rotation_to_z = fc.Rotation()
        for ros_joint in ros_joints:
            name = list(joint_map.keys())[list(joint_map.values()).index(ros_joint)]
            urdf_joint = urdf_robot.joint_map[name]
            rotation_to_z = axis_to_z(urdf_joint)
            if ros_joint in already_compensated_joints:
                previous_rotation_to_z = rotation_to_z
                continue
            already_compensated_joints.add(ros_joint)
            _set_child_placement(robot, urdf_joint, ros_joint)
            ros_joint.Origin = previous_rotation_to_z.inverted() * ros_joint.Origin
            previous_rotation_to_z = rotation_to_z


def _set_child_placement(
        robot: RosRobot,
        urdf_joint: UrdfJoint,
        ros_joint: RosJoint,
        ) -> None:
    """Set Child.MountedPlacement to compensate for joints not along z."""
    if not ros_joint.Child:
        return
    link = robot.Proxy.get_link(ros_joint.Child)
    if link:
        link.MountedPlacement.Rotation = axis_to_z(urdf_joint).inverted()


def _add_visual(
        urdf_link: UrdfLink,
        parts_group: DOG,
        ros_link: RosLink,
        visual_part: AppPart,
        ) -> tuple[DOList, DOList]:
    """Add the visual geometries to an assembly.

    Return the list of objects representing the geometries and the list of
    FreeCAD links.

    Parameters
    ==========

    - robot: an UrdfRobot.

    """
    name_linked_geom = f'{urdf_link.name}_visual'
    return _add_geometries(parts_group,
                           ros_link,
                           visual_part,
                           urdf_link.visuals,
                           name_linked_geom)


def _add_collision(
        urdf_link: UrdfLink,
        parts_group: DOG,
        ros_link: RosLink,
        collision_part: AppPart,
        ) -> tuple[DOList, DOList]:
    """Add the visual geometries to an assembly.

    Return the list of objects representing the geometries and the list of
    FreeCAD links.

    Parameters
    ==========

    - robot: an UrdfRobot.

    """
    name_linked_geom = f'{urdf_link.name}_collision'
    return _add_geometries(parts_group, ros_link,
                           collision_part, urdf_link.collisions, name_linked_geom)


def _add_geometries(
        parts_group: DOG,
        ros_link: DOG,
        part: AppPart,
        geometries: [VisualList | CollisionList],
        name_linked_geom: str,
        ) -> tuple[DOList, DOList]:
    """Add the geometries from URDF into `group` and an App::Link to it into `link`.

    `geometries` is either `visuals` or `collisions` and the geometry itself is
    `geometries[?].geometry`.
    If `name_linked_geom` is empty, not FC link is created in `link`.

    Return the list of objects representing the geometries and the list of
    FreeCAD links.

    Parameters
    ==========

    - group: an "App::DocumentObjectGroup" where the generated FreeCAD objects
             will be placed.
    - geometries: list of URDF geometries.
    - link: an "App::Link" object linking to an "App::Part" object representing
            the visual- or collision geometries of a URDF link.
    - name_linked_geom: base pattern for the generated "App::Link" objects
                        generated. The final name may then be
                        `name_linked_geom`, `name_linked_geom`001, ...

    """
    geom_objs: DOList = []
    links: DOList = []
    for geometry in geometries:
        # Make the FC object in the group.
        try:
            geom_obj, _ = obj_from_geometry(geometry.geometry, parts_group)
        except NotImplementedError:
            continue
        if not geom_obj:
            warn(f'Error when importing geometry for {ros_link.Label}')
            continue
        geom_obj.Visibility = False
        geom_objs.append(geom_obj)
        if hasattr(geometry, 'origin'):
            geom_obj.Placement = (placement_from_origin(geometry.origin)
                                  * geom_obj.Placement)
        # Add a reference to geom_obj to `ros_link.Visual` or
        # `ros_link.Collision`.
        link_to_geom = add_object(part, 'App::Link', name_linked_geom)
        link_to_geom.setLink(geom_obj)
        link_to_geom.Placement = geom_obj.Placement
        links.append(link_to_geom)
    return geom_objs, links
