#!/usr/bin/env python3
"""
HomeKit Bridge Manager for Home Assistant

A tool to manage HomeKit bridges with area-based entity organization,
helping stay under the 150 device per bridge limit.

Usage:
    python3 homekit_bridge_manager.py generate    # Generate entity mapping
    python3 homekit_bridge_manager.py apply       # Apply config (stops/starts HA)
    python3 homekit_bridge_manager.py validate    # Validate current config
    python3 homekit_bridge_manager.py list        # List current bridges

Configuration:
    Edit config.yaml to define bridges, excluded integrations, and paths.

License: MIT
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import yaml

# Default configuration
DEFAULT_CONFIG = {
    "ha_config_path": "/srv/HA/ha-config",
    "ha_service": "home-assistant@homeassistant",
    "output_dir": ".",

    "excluded_integrations": [
        "unifi",
        "unifiprotect",
        "alexa_media",
        "frigate",
        "sonos",
        "stateful_scenes",
        "nest_protect",
        "adguard",
        "pura",
        "spook",
        "rachio",
        "litterrobot",
        "bambu_lab",
        "teslemetry",
        "wake_on_lan",
        "synology_dsm",
        "hacs",
    ],

    "excluded_patterns": [
        r"_segment_\d{3}",  # Govee segments (001, 002, etc.)
    ],

    "ignored_entities": [
        # Specific entities to always exclude
        # Example: "switch.some_device_i_dont_want"
    ],

    "bridges": [
        # Example bridge configuration
        # {
        #     "name": "First Floor",
        #     "areas": ["Kitchen", "Living Room", "Family Room"]
        # }
    ]
}


class HomeKitBridgeManager:
    def __init__(self, config_path=None):
        self.config = self._load_config(config_path)
        self.ha_path = Path(self.config["ha_config_path"])
        self.storage_path = self.ha_path / ".storage"
        self.output_dir = Path(self.config["output_dir"])

    def _load_config(self, config_path):
        """Load configuration from YAML file or use defaults"""
        config = DEFAULT_CONFIG.copy()

        if config_path and Path(config_path).exists():
            with open(config_path) as f:
                user_config = yaml.safe_load(f)
                if user_config:
                    config.update(user_config)

        return config

    def _load_registry(self, name):
        """Load a registry file from .storage"""
        path = self.storage_path / f"core.{name}"
        if not path.exists():
            print(f"❌ Registry not found: {path}")
            sys.exit(1)
        with open(path) as f:
            return json.load(f)

    def _should_include_entity(self, entity_id, platform):
        """Check if entity should be included based on filters"""
        # Check explicit ignore list
        if entity_id in self.config.get("ignored_entities", []):
            return False

        # Check integration exclusions
        if platform in self.config.get("excluded_integrations", []):
            return False

        # Check pattern exclusions
        for pattern in self.config.get("excluded_patterns", []):
            if re.search(pattern, entity_id):
                return False

        return True

    def generate(self):
        """Generate entity-to-bridge mapping"""
        print("=" * 70)
        print("Generating HomeKit Bridge Mapping")
        print("=" * 70)

        # Load registries
        entity_reg = self._load_registry("entity_registry")
        device_reg = self._load_registry("device_registry")
        area_reg = self._load_registry("area_registry")

        # Build lookups
        area_map = {a["id"]: a["name"] for a in area_reg["data"]["areas"]}
        device_to_area = {d["id"]: d.get("area_id") for d in device_reg["data"]["devices"]}

        # Build entity info
        entity_names = {}
        entity_platforms = {}

        for entity in entity_reg["data"]["entities"]:
            eid = entity["entity_id"]
            entity_names[eid] = entity.get("name") or entity.get("original_name") or eid.split(".")[1].replace("_", " ").title()
            entity_platforms[eid] = entity.get("platform", "unknown")

        # Map entities to bridges
        bridge_entities = defaultdict(lambda: {"lights": [], "switches": []})
        no_area_entities = {"lights": [], "switches": []}
        excluded_count = defaultdict(int)

        for entity in entity_reg["data"]["entities"]:
            # Skip disabled
            if entity.get("disabled_by") is not None:
                continue

            entity_id = entity["entity_id"]
            platform = entity.get("platform", "unknown")

            # Only lights and switches
            if not (entity_id.startswith("light.") or entity_id.startswith("switch.")):
                continue

            # Apply filters
            if not self._should_include_entity(entity_id, platform):
                excluded_count[platform] += 1
                continue

            # Get area
            area_id = entity.get("area_id")
            if not area_id and entity.get("device_id"):
                area_id = device_to_area.get(entity.get("device_id"))

            area_name = area_map.get(area_id) if area_id else None

            # Assign to bridge
            domain = "lights" if entity_id.startswith("light.") else "switches"
            assigned = False

            for bridge in self.config["bridges"]:
                if area_name in bridge.get("areas", []):
                    bridge_entities[bridge["name"]][domain].append({
                        "id": entity_id,
                        "name": entity_names.get(entity_id, "Unknown")
                    })
                    assigned = True
                    break

            if not assigned:
                no_area_entities[domain].append({
                    "id": entity_id,
                    "name": entity_names.get(entity_id, "Unknown")
                })

        # Sort entities
        for bridge_name in bridge_entities:
            bridge_entities[bridge_name]["lights"].sort(key=lambda x: x["id"])
            bridge_entities[bridge_name]["switches"].sort(key=lambda x: x["id"])

        # Save mapping
        mapping = {
            "bridges": dict(bridge_entities),
            "no_area": no_area_entities,
            "generated_at": datetime.now().isoformat()
        }

        output_file = self.output_dir / "homekit_mapping.json"
        with open(output_file, "w") as f:
            json.dump(mapping, f, indent=2)

        # Print summary
        print(f"\n✓ Mapping saved: {output_file}")

        total_included = 0
        print("\nBridge Summary:")
        for bridge in self.config["bridges"]:
            name = bridge["name"]
            if name in bridge_entities:
                lights = len(bridge_entities[name]["lights"])
                switches = len(bridge_entities[name]["switches"])
                total = lights + switches
                total_included += total
                status = "✅" if total <= 150 else "❌ OVER LIMIT"
                print(f"  {name}: {total} entities ({lights} lights, {switches} switches) {status}")

        if excluded_count:
            print(f"\nExcluded {sum(excluded_count.values())} entities by integration")

        print(f"\nUnassigned: {len(no_area_entities['lights']) + len(no_area_entities['switches'])} entities")

        return mapping

    def apply(self, dry_run=False):
        """Apply mapping to Home Assistant config"""
        print("=" * 70)
        print("Applying HomeKit Bridge Configuration")
        print("=" * 70)

        # Load mapping
        mapping_file = self.output_dir / "homekit_mapping.json"
        if not mapping_file.exists():
            print(f"❌ Mapping file not found: {mapping_file}")
            print("   Run 'generate' first")
            return False

        with open(mapping_file) as f:
            mapping = json.load(f)

        # Load current config
        config_path = self.storage_path / "core.config_entries"
        with open(config_path) as f:
            config = json.load(f)

        # Find bridge entry IDs by name
        bridge_entries = {}
        for entry in config["data"]["entries"]:
            if entry.get("domain") == "homekit":
                bridge_entries[entry.get("title")] = entry

        # Stop HA if not dry run
        if not dry_run:
            print("\nStopping Home Assistant...")
            result = subprocess.run(
                ["sudo", "systemctl", "stop", self.config["ha_service"]],
                capture_output=True
            )
            if result.returncode != 0:
                print(f"❌ Failed to stop HA: {result.stderr.decode()}")
                return False
            print("✓ Home Assistant stopped")

            # Create backup
            backup_path = config_path.parent / f"core.config_entries.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            shutil.copy2(config_path, backup_path)
            print(f"✓ Backup: {backup_path.name}")

        # Update each bridge
        print("\nUpdating bridges:")
        for bridge in self.config["bridges"]:
            name = bridge["name"]

            if name not in bridge_entries:
                print(f"  ⚠️  {name}: Not found in HA config (create it first)")
                continue

            entry = bridge_entries[name]
            bridge_data = mapping["bridges"].get(name, {"lights": [], "switches": []})

            # Build include list
            include_list = sorted(
                [e["id"] for e in bridge_data["lights"]] +
                [e["id"] for e in bridge_data["switches"]]
            )

            # Update filter config
            if "options" not in entry:
                entry["options"] = {}
            if "filter" not in entry["options"]:
                entry["options"]["filter"] = {}

            entry["options"]["filter"]["include_domains"] = []
            entry["options"]["filter"]["exclude_domains"] = []
            entry["options"]["filter"]["include_entities"] = include_list
            entry["options"]["filter"]["exclude_entities"] = []
            entry["modified_at"] = datetime.utcnow().isoformat() + "+00:00"

            print(f"  ✅ {name}: {len(include_list)} entities")

        # Save config
        if not dry_run:
            with open(config_path, "w") as f:
                json.dump(config, f, indent=2)
            print("\n✓ Configuration saved")

            # Start HA
            print("\nStarting Home Assistant...")
            result = subprocess.run(
                ["sudo", "systemctl", "start", self.config["ha_service"]],
                capture_output=True
            )
            if result.returncode != 0:
                print(f"❌ Failed to start HA: {result.stderr.decode()}")
                return False
            print("✓ Home Assistant started")
        else:
            print("\n(Dry run - no changes made)")

        return True

    def analyze(self):
        """Analyze areas and suggest bridge groupings"""
        print("=" * 70)
        print("Analyzing Home Assistant for Bridge Planning")
        print("=" * 70)

        # Load registries
        entity_reg = self._load_registry("entity_registry")
        device_reg = self._load_registry("device_registry")
        area_reg = self._load_registry("area_registry")
        floor_reg_path = self.storage_path / "core.floor_registry"

        # Build lookups
        area_map = {a["id"]: a["name"] for a in area_reg["data"]["areas"]}
        area_floors = {a["id"]: a.get("floor_id") for a in area_reg["data"]["areas"]}
        device_to_area = {d["id"]: d.get("area_id") for d in device_reg["data"]["devices"]}

        # Load floors if available
        floor_map = {}
        if floor_reg_path.exists():
            with open(floor_reg_path) as f:
                floor_reg = json.load(f)
                floor_map = {f["floor_id"]: f["name"] for f in floor_reg["data"]["floors"]}

        # Count entities per area
        area_counts = defaultdict(lambda: {"lights": 0, "switches": 0, "floor": None})

        for entity in entity_reg["data"]["entities"]:
            if entity.get("disabled_by") is not None:
                continue

            entity_id = entity["entity_id"]
            platform = entity.get("platform", "unknown")

            if not (entity_id.startswith("light.") or entity_id.startswith("switch.")):
                continue

            if not self._should_include_entity(entity_id, platform):
                continue

            # Get area
            area_id = entity.get("area_id")
            if not area_id and entity.get("device_id"):
                area_id = device_to_area.get(entity.get("device_id"))

            if area_id:
                area_name = area_map.get(area_id, "Unknown")
                domain = "lights" if entity_id.startswith("light.") else "switches"
                area_counts[area_name][domain] += 1

                # Track floor
                floor_id = area_floors.get(area_id)
                if floor_id and floor_id in floor_map:
                    area_counts[area_name]["floor"] = floor_map[floor_id]

        # Group by floor
        floors = defaultdict(list)
        no_floor = []

        for area_name, counts in sorted(area_counts.items()):
            total = counts["lights"] + counts["switches"]
            floor = counts["floor"]

            area_info = {
                "name": area_name,
                "lights": counts["lights"],
                "switches": counts["switches"],
                "total": total
            }

            if floor:
                floors[floor].append(area_info)
            else:
                no_floor.append(area_info)

        # Print analysis
        print("\n" + "=" * 70)
        print("Entity Counts by Area (after filtering)")
        print("=" * 70)

        total_entities = 0

        for floor_name in sorted(floors.keys()):
            areas = floors[floor_name]
            floor_total = sum(a["total"] for a in areas)
            total_entities += floor_total

            print(f"\n📍 {floor_name} ({floor_total} entities)")
            for area in sorted(areas, key=lambda x: -x["total"]):
                print(f"   {area['name']}: {area['total']} ({area['lights']}L, {area['switches']}S)")

        if no_floor:
            floor_total = sum(a["total"] for a in no_floor)
            total_entities += floor_total
            print(f"\n📍 No Floor Assigned ({floor_total} entities)")
            for area in sorted(no_floor, key=lambda x: -x["total"]):
                print(f"   {area['name']}: {area['total']} ({area['lights']}L, {area['switches']}S)")

        # Suggest bridge groupings
        print("\n" + "=" * 70)
        print("Suggested Bridge Configuration")
        print("=" * 70)

        bridges_needed = (total_entities // 150) + (1 if total_entities % 150 else 0)
        print(f"\nTotal entities: {total_entities}")
        print(f"Minimum bridges needed: {bridges_needed} (to stay under 150 each)")

        # Simple suggestion: group by floor
        print("\n📋 Suggested bridges (by floor):\n")

        suggested_bridges = []
        for floor_name in sorted(floors.keys()):
            areas = floors[floor_name]
            floor_total = sum(a["total"] for a in areas)

            if floor_total <= 150:
                # Single bridge for this floor
                suggested_bridges.append({
                    "name": floor_name,
                    "areas": [a["name"] for a in areas],
                    "count": floor_total
                })
            else:
                # Need to split this floor
                current_bridge = {"name": f"{floor_name} A", "areas": [], "count": 0}
                bridge_num = 1

                for area in sorted(areas, key=lambda x: -x["total"]):
                    if current_bridge["count"] + area["total"] > 150:
                        # Save current and start new
                        if current_bridge["areas"]:
                            suggested_bridges.append(current_bridge)
                        bridge_num += 1
                        suffix = chr(ord('A') + bridge_num - 1)
                        current_bridge = {"name": f"{floor_name} {suffix}", "areas": [], "count": 0}

                    current_bridge["areas"].append(area["name"])
                    current_bridge["count"] += area["total"]

                if current_bridge["areas"]:
                    suggested_bridges.append(current_bridge)

        # Print suggestions
        for bridge in suggested_bridges:
            status = "✅" if bridge["count"] <= 150 else "❌"
            print(f"{status} {bridge['name']}: {bridge['count']} entities")
            print(f"   Areas: {', '.join(bridge['areas'])}")
            print()

        # Generate config snippet
        print("=" * 70)
        print("Config.yaml snippet:")
        print("=" * 70)
        print("\nbridges:")
        for bridge in suggested_bridges:
            print(f"  - name: {bridge['name']}")
            print(f"    areas:")
            for area in bridge["areas"]:
                print(f"      - {area}")
            print()

        return suggested_bridges

    def validate(self):
        """Validate current HomeKit bridge configuration"""
        print("=" * 70)
        print("Validating HomeKit Bridge Configuration")
        print("=" * 70)

        config = self._load_registry("config_entries")

        print("\nCurrent Bridges:")
        for entry in config["data"]["entries"]:
            if entry.get("domain") != "homekit":
                continue

            name = entry.get("title", "Unknown")
            filter_config = entry.get("options", {}).get("filter", {})

            include_entities = len(filter_config.get("include_entities", []))
            exclude_entities = len(filter_config.get("exclude_entities", []))
            include_domains = filter_config.get("include_domains", [])

            if include_entities > 0:
                mode = "Include"
                count = include_entities
            elif include_domains:
                mode = "Domain"
                count = "all " + ", ".join(include_domains)
            else:
                mode = "Unknown"
                count = "?"

            status = "✅" if (isinstance(count, int) and count <= 150) else ""
            print(f"  {name}: {count} entities ({mode} mode) {status}")

    def list_bridges(self):
        """List available bridges and their entry IDs"""
        print("=" * 70)
        print("HomeKit Bridges in Home Assistant")
        print("=" * 70)

        config = self._load_registry("config_entries")

        print("\nBridges:")
        for entry in config["data"]["entries"]:
            if entry.get("domain") != "homekit":
                continue

            name = entry.get("title", "Unknown")
            entry_id = entry.get("entry_id", "Unknown")
            port = entry.get("data", {}).get("port", "?")

            print(f"  {name}")
            print(f"    Entry ID: {entry_id}")
            print(f"    Port: {port}")
            print()


def main():
    parser = argparse.ArgumentParser(
        description="HomeKit Bridge Manager for Home Assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s analyze               Analyze areas and suggest bridge groupings
  %(prog)s generate              Generate entity mapping from config
  %(prog)s apply                 Apply mapping to HA (stops/starts HA)
  %(prog)s apply --dry-run       Preview changes without applying
  %(prog)s validate              Check current bridge configuration
  %(prog)s list                  List all HomeKit bridges
  %(prog)s init                  Create example config.yaml
        """
    )

    parser.add_argument("command", choices=["analyze", "generate", "apply", "validate", "list", "init"],
                        help="Command to run")
    parser.add_argument("-c", "--config", default="config.yaml",
                        help="Path to config file (default: config.yaml)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes without applying")

    args = parser.parse_args()

    if args.command == "init":
        # Create example config
        example_config = {
            "ha_config_path": "/srv/HA/ha-config",
            "ha_service": "home-assistant@homeassistant",
            "output_dir": ".",

            "excluded_integrations": DEFAULT_CONFIG["excluded_integrations"],
            "excluded_patterns": DEFAULT_CONFIG["excluded_patterns"],

            "bridges": [
                {
                    "name": "First Floor",
                    "areas": ["Kitchen", "Living Room", "Family Room"]
                },
                {
                    "name": "Second Floor",
                    "areas": ["Master Bedroom", "Kids Bedroom", "Bathroom"]
                }
            ]
        }

        with open("config.yaml", "w") as f:
            yaml.dump(example_config, f, default_flow_style=False, sort_keys=False)

        print("✓ Created config.yaml")
        print("  Edit this file to configure your bridges and settings")
        return

    manager = HomeKitBridgeManager(args.config)

    if args.command == "analyze":
        manager.analyze()
    elif args.command == "generate":
        manager.generate()
    elif args.command == "apply":
        manager.apply(dry_run=args.dry_run)
    elif args.command == "validate":
        manager.validate()
    elif args.command == "list":
        manager.list_bridges()


if __name__ == "__main__":
    main()
