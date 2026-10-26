"""
Description: [Add module purpose here]

Author: Robin
Created: 10.02.2026
Copyright: © 2026 Robin Dönnebrink
"""

from typing import Iterable, Mapping
from xml.etree import ElementTree as ET


def prettify(elem: ET.Element) -> str:
    """Kompaktes XML ohne Kopfzeile und Einrueckung, genau wie in der Referenzdatei von JAuswertung."""
    return ET.tostring(elem, encoding="unicode")


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


def create_empty_lane(entry_parent: ET.Element, lane_index: int) -> None:
    """Leere Bahn ohne Zeit. JAuswertung erwartet die Bahnen lueckenlos ab 0."""
    entry: ET.Element = ET.SubElement(entry_parent, "entry")
    ET.SubElement(entry, "int").text = str(lane_index)
    lane: ET.Element = ET.SubElement(entry, "AlphaServer.Lane")
    ET.SubElement(lane, "laneindex").text = str(lane_index)
    ET.SubElement(lane, "times")
    ET.SubElement(lane, "stati")


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
    # Lanes are zero-based; Luecken werden mit leeren Bahnen gefuellt
    zero_based = {lane_index - 1: time_value for lane_index, time_value in lane_times.items()}
    for lane_index in range(0, max(zero_based, default=-1) + 1):
        if lane_index in zero_based:
            create_lane(lanes, lane_index, zero_based[lane_index])
        else:
            create_empty_lane(lanes, lane_index)

    # Set the event number for this heat.
    event: ET.Element = ET.SubElement(heat, "event")
    event.text = str(event_number)

    # Set the heat number (within the event).
    heat_elem: ET.Element = ET.SubElement(heat, "heat")
    heat_elem.text = str(heat_number)


def create_xml_heats(heats: Iterable[tuple[int, int, Mapping[int, int]]]) -> str:
    """
    Erzeugt das AlphaServer-XML fuer JAuswertung.

    heats: Liste aus (Wettkampf, Lauf im Wettkampf, {Bahn (1-basiert): Zeit in ms}).
    """
    root = ET.Element("AlphaServer.Heat-array")

    for event_number, heat_number, lane_times in heats:
        create_heat(
            parent=root,
            event_number=event_number,
            heat_number=heat_number,
            lane_times=lane_times,
        )

    return prettify(root)
