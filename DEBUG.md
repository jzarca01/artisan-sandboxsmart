
### Install the package (editable mode)

```bash
pip install -e ".[dev]"
```

### Run the CLI (with either the device name or address):

```bash
# Using device name
artisan-sandbox-cli --name <device-name>

# Using device address
artisan-sandbox-cli --address <device-address>

# For macOS users
artisan-sandbox-cli --address <device-address> --macos-use-bdaddr
```

#### Command Line Arguments

- `--name <name>`: Connect to device by name
- `--address <address>`: Connect to device by Bluetooth address
- `--macos-use-bdaddr`: Use Bluetooth address instead of UUID on macOS
- `-d, --debug`: Enable debug logging

#### Available Commands

Once connected, you can use the following commands through the interactive menu:

- `HEAT 0-100` - Set heat power
- `DRUM 0-100` - Set drum speed
- `DRAW 0-100` - Set fan speed
- `LIGHT ON` / `LIGHT OFF` - Control lights
- `HPTEMP` - Get current temperature
- `HSTOP` - Stop the roaster
- `COOLING` - Activate cooling cycle
- `HPSTART 1200 200` - Start preheating (time / temperature)
- `PREHEAT [TARGET_TEMPERATURE] [SOAK_DURATION] [TOLERANCE] [TIMEOUT]` - Preheat with soak check (target temp) with optional timeout: `PREHEAT 200 1800 5 1200`
- `PREHEAT_STOP` - Stop preheating
- `HSTART` - Start roasting
- `EXIT` - Exit the application

### Run the WebSocket server

```bash
artisan-sandbox-server -m <device-mac-address>
artisan-sandbox-server -m <device-mac-address> -d  # with debug logging
```

### Run the websockets client (optional, only for debug)

```bash
artisan-sandbox-cli-ws --url ws://localhost:8765
```