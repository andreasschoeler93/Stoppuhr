"""
Description: [Add module purpose here]

Author: Robin
Created: 10.02.2026
Copyright: © 2026 Robin Dönnebrink
"""

from typing import Mapping
from xml.dom import minidom
from xml.etree import ElementTree as ET


# ToDo: Move LinesPerRun to seperaze class
# from app import LaneTimesPerRun

# Todo: Discuss with MaOl if lanes have to start at 0 in XML


def prettify(elem: ET.Element) -> str:
    """Return a pretty-printed XML string for an ElementTree element."""
    # Serialize the ElementTree element (and its subtree) into raw XML bytes.
    rough_string: bytes = ET.tostring(elem, encoding="utf-8")

    # Re-parse the bytes with minidom so we can use its pretty printer.
    reparsed = minidom.parseString(rough_string)

    # Produce indented XML (two spaces per level).
    return reparsed.toprettyxml(indent="  ")


def create_lane(entry_parent: ET.Element, lane_index: int, time_value: int) -> None:
    """
    Append one lane entry to the given parent XML element.

    The resulting structure looks like a map entry:
      <entry>
        <int>{lane_index}</int>
        <AlphaServer.Lane>...</AlphaServer.Lane>
      </entry>
    """
    # Create one map-like "entry" element under the provided parent node.
    entry: ET.Element = ET.SubElement(entry_parent, "entry")

    # Add the key part of the entry: <int>{lane_index}</int>
    key: ET.Element = ET.SubElement(entry, "int")
    key.text = str(lane_index)

    # Add the value part of the entry: an AlphaServer.Lane object.
    lane: ET.Element = ET.SubElement(entry, "AlphaServer.Lane")

    # Store the lane index inside the lane object as well.
    laneindex: ET.Element = ET.SubElement(lane, "laneindex")
    laneindex.text = str(lane_index)

    # Create <times> with one <long> value representing the time for this lane.
    times: ET.Element = ET.SubElement(lane, "times")
    time_elem: ET.Element = ET.SubElement(times, "long")
    time_elem.text = str(time_value)

    # Create <stati> with a single lane status value.
    stati: ET.Element = ET.SubElement(lane, "stati")
    status: ET.Element = ET.SubElement(stati, "AlphaServer.LaneStatus")

    # Domain-specific status label (likely an enum-like value expected by the consumer).
    status.text = "RaceTimes"


def create_heat(
    parent: ET.Element,
    event_number: int,
    heat_number: int,
    lane_times: Mapping[int, int],
) -> None:
    """
    Append a heat element under `parent`, including lane data and identifiers.

    Args:
        parent: The XML element under which the heat is created.
        event_number: Event identifier to store in <event>.
        heat_number: Heat identifier to store in <heat>.
        lane_times: Mapping of lane_index -> time_value (written as <long>).
    """
    # Create a new heat object under the provided parent element.
    heat: ET.Element = ET.SubElement(parent, "AlphaServer.Heat")

    # Create the container that holds lane entries for this heat.
    lanes: ET.Element = ET.SubElement(heat, "lanes")

    # Add one lane entry per mapping item.
    for lane_index, time_value in lane_times.items():
        create_lane(lanes, lane_index, time_value)

    # Set the event number for this heat.
    event: ET.Element = ET.SubElement(heat, "event")
    event.text = str(event_number)

    # Set the heat number (within the event).
    heat_elem: ET.Element = ET.SubElement(heat, "heat")
    heat_elem.text = str(heat_number)


def create_xml_heats(heats_data) -> str:
    root = ET.Element("AlphaServer.Heat-array")

    for run, lane_times in heats_data.items():
        create_heat(
            parent=root,
            event_number=run,
            heat_number=3,  # In my example heats.xml this is always 3: ToDo: Determine why? MaOl
            lane_times=lane_times,
        )

    xml_output = prettify(root)

    return xml_output
