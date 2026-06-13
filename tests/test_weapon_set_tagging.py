"""
Tests for weapon-set tagging in the PoB importer (backlog item).

PoE2 weapon swap means set-specific weapon stats only apply on the
active set. Flattening both sets into one gear list wrongly attributes
swap-set stats (e.g. a swap staff's chaos/spirit) to the active build.
Tagging each item with weapon_set is the data foundation for fixing
that in the analyze_character formatter (follow-up, mcp_server.py).
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pob.importer import PoBImporter


def test_weapon_set_for_slot_mapping():
    f = PoBImporter._weapon_set_for_slot
    assert f("Weapon 1") == 1
    assert f("Weapon 2") == 1
    assert f("Weapon 1 Swap") == 2
    assert f("Weapon 2 Swap") == 2
    assert f("Body Armour") is None
    assert f("Ring 1") is None
    assert f("Amulet") is None
    assert f(None) is None


# Minimal PoB XML mirroring the commander's TomawarTheSeventh layout:
# set 1 = wand + sceptre, set 2 (swap) = a chaos two-hander.
SAMPLE_XML = """<PathOfBuilding>
  <Build level="90" className="Witch" ascendClassName="Infernalist"/>
  <Skills></Skills>
  <Tree><Spec nodes="1,2"/></Tree>
  <Items>
    <ItemSet useSecondWeaponSet="false" title="Default" id="1">
      <Slot name="Weapon 1" itemId="1"/>
      <Slot name="Weapon 2" itemId="2"/>
      <Slot name="Weapon 1 Swap" itemId="3"/>
      <Slot name="Body Armour" itemId="4"/>
    </ItemSet>
    <Item id="1">Rarity: RARE
Torment Song
Wand
+6 to Level of all Fire Spell Skills</Item>
    <Item id="2">Rarity: UNIQUE
The Dark Defiler
Rattling Sceptre
15% increased Spirit</Item>
    <Item id="3">Rarity: UNIQUE
The Unborn Lich
Staff
195% increased Chaos Damage
+86 to Spirit</Item>
    <Item id="4">Rarity: RARE
Necromantle
Conjurer Mantle
+55 to maximum Life</Item>
  </Items>
</PathOfBuilding>"""


def test_items_tagged_with_weapon_set():
    build = PoBImporter().import_xml_sync(SAMPLE_XML)
    by_name = {i["name"]: i for i in build["items"]}
    assert by_name["Torment Song"]["weapon_set"] == 1       # Weapon 1
    assert by_name["The Dark Defiler"]["weapon_set"] == 1   # Weapon 2 (still set 1)
    assert by_name["The Unborn Lich"]["weapon_set"] == 2    # Weapon 1 Swap = set 2
    assert by_name["Necromantle"]["weapon_set"] is None     # body armour, set-independent


def test_swap_set_item_separable():
    """The exact bug from the build conversation: the swap staff's chaos
    must be attributable to set 2, not flattened into the active build."""
    build = PoBImporter().import_xml_sync(SAMPLE_XML)
    set1 = [i for i in build["items"] if i.get("weapon_set") == 1]
    set2 = [i for i in build["items"] if i.get("weapon_set") == 2]
    set1_names = {i["name"] for i in set1}
    set2_names = {i["name"] for i in set2}
    assert "The Unborn Lich" in set2_names
    assert "The Unborn Lich" not in set1_names   # never both
    assert "Torment Song" in set1_names
