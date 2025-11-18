# HomeKit Bridge Manager

A tool to manage HomeKit bridges in Home Assistant with area-based entity organization, helping stay under the 150 device per bridge limit.

## The Problem

HomeKit has a hard limit of 150 accessories per bridge. When your Home Assistant instance has hundreds of lights and switches, you need multiple bridges organized intelligently to stay under this limit.

This tool:
- Maps entities to bridges based on room/area assignments
- Filters out virtual switches (Alexa controls, camera settings, etc.)
- Uses clean "include mode" instead of massive exclusion lists
- Generates human-readable mappings with friendly names
- Handles the stop/apply/start cycle automatically

## Quick Start

```bash
# 1. Install dependencies
pip install pyyaml

# 2. Create your config
python3 homekit_bridge_manager.py init
# Edit config.yaml with your bridges and areas

# 3. Generate the mapping
python3 homekit_bridge_manager.py generate

# 4. Review homekit_mapping.json and edit if needed

# 5. Apply to Home Assistant (will stop/start HA)
sudo python3 homekit_bridge_manager.py apply

# Or preview first
python3 homekit_bridge_manager.py apply --dry-run
```

## Commands

| Command | Description |
|---------|-------------|
| `init` | Create example config.yaml |
| `generate` | Generate entity mapping from areas |
| `apply` | Apply mapping to HA config (stops/starts HA) |
| `validate` | Check current bridge configuration |
| `list` | List all HomeKit bridges and entry IDs |

## Configuration

Edit `config.yaml` to define:

### Bridges
Map Home Assistant areas to bridges:

```yaml
bridges:
  - name: First Floor
    areas:
      - Kitchen
      - Living Room
      - Family Room

  - name: Second Floor
    areas:
      - Master Bedroom
      - Kids Bedroom
```

### Excluded Integrations
Virtual switches that shouldn't be in HomeKit:

```yaml
excluded_integrations:
  - alexa_media     # Shuffle/repeat/DND switches
  - unifi           # Network device access
  - frigate         # Camera detection settings
  - sonos           # Audio settings
```

### Excluded Patterns
Regex patterns to filter out:

```yaml
excluded_patterns:
  - '_segment_\d{3}'  # Govee LED segments
```

## Prerequisites

1. **Create bridges in Home Assistant first** - The tool updates existing bridges, it doesn't create them
2. **Bridges must be named exactly** - Match the `name` field in config.yaml
3. **Assign areas to devices** - Entities inherit areas from their devices

## How It Works

1. **Generate**: Reads HA registries, maps entities to bridges by area, filters by integration
2. **Apply**: Stops HA, updates `.storage/core.config_entries` with include lists, starts HA

The tool uses "include mode" - each bridge gets an explicit list of entities to expose, rather than listing everything to exclude.

## Output Files

- `homekit_mapping.json` - Entity-to-bridge mapping with friendly names
- `config.yaml` - Your configuration
- Backups created in `.storage/` before each apply

## Example Workflow

```bash
# First time setup
python3 homekit_bridge_manager.py init
vim config.yaml  # Define your bridges

# Generate and review
python3 homekit_bridge_manager.py generate
cat homekit_mapping.json | jq '.bridges["First Floor"]'

# Edit mapping if needed (remove entities, etc.)
vim homekit_mapping.json

# Apply
sudo python3 homekit_bridge_manager.py apply

# Verify
python3 homekit_bridge_manager.py validate
```

## Re-running After Changes

If you add new devices or change areas:

```bash
python3 homekit_bridge_manager.py generate
# Review/edit homekit_mapping.json
sudo python3 homekit_bridge_manager.py apply
```

## Troubleshooting

**Bridge not found**: Create it in HA first (Settings > Devices & Services > Add Integration > HomeKit)

**Wrong entity count**: Check that devices have areas assigned in HA

**Entities missing**: Check `excluded_integrations` and `excluded_patterns` in config

**Permission denied**: Run apply with `sudo`

## License

MIT License - Feel free to use, modify, and distribute.

## Credits

Built to solve the HomeKit 150-device limit problem for complex Home Assistant installations.
