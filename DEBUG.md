
### Run the CLI (with either the device name or address):

```bash
# Using device name
python3 cli.py --name <device-name>

# Using device address
python3 cli.py --address <device-address>

# For macOS users
python3 cli.py --address <device-address> --macos-use-bdaddr
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
- `HSTART` - Start roasting
- `EXIT` - Exit the application

### Run the websockets client (optional, only for debug)

```bash
python3 cli_ws.py --url ws://localhost:8765
```