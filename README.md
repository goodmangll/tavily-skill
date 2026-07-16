# Tavily Skill

A cross-platform AI agent skill for Tavily web search, URL extraction, site mapping, crawling, and
deep research. The CLI is Python 3 standard library only; it has no runtime package dependencies.

## Supported Platforms

| Platform | Package metadata |
|---|---|
| [Pi](https://pi.dev) | `package.json` `pi` manifest |
| Claude Code | `adapters/claude/plugin.json` |
| Codex | `adapters/codex/plugin.json` |
| Cursor | `adapters/cursor/config.json` |

The platform-agnostic source of truth is [`skills/tavily/`](skills/tavily/). Adapters only provide
platform-specific discovery metadata; the skill instructions and CLI are not duplicated.

## Configuration

Get a Tavily API key at [tavily.com](https://tavily.com), then create:

```text
${XDG_CONFIG_HOME:-~/.config}/tavily/config.yaml
```

```yaml
api_keys:
  - tvly-dev-xxx1
  - tvly-dev-xxx2

# Optional: override the generated-result directory.
# output_dir: ~/.local/share/tavily/results
```

The CLI follows the XDG Base Directory specification:

| Purpose | Default location |
|---|---|
| User configuration | `${XDG_CONFIG_HOME:-~/.config}/tavily/config.yaml` |
| Runtime state | `${XDG_STATE_HOME:-~/.local/state}/tavily/state.json` |
| Results | `${XDG_DATA_HOME:-~/.local/share}/tavily/results/` |

Keep `config.yaml` outside this repository. It contains your API credentials.

## Install

### Pi

From a local checkout:

```bash
pi install /path/to/tavily-skill
```

From Git after publishing:

```bash
pi install git:github.com/<owner>/tavily-skill
```

Pi loads the skill from the `skills/` directory declared in `package.json`.

### Claude Code, Codex, and Cursor

Install this repository using each platform's plugin or skill workflow, pointing it at the respective
metadata file under `adapters/`. Each adapter references the common `skills/` directory.

## Direct CLI Usage

```bash
cd skills/tavily
python3 tavily.py search "latest AI news"
python3 tavily.py extract https://example.com
python3 tavily.py map --url docs.tavily.com
python3 tavily.py crawl --url docs.tavily.com
python3 tavily.py research create --input "Latest AI regulation developments" --wait
```

By default, JSON output is saved under the XDG data directory. Add `--stdout` to print the complete
payload inline, or use `--output <path>` to select a file location.

## Development

```bash
npm test
npm run check
npm pack --dry-run
```

`npm test` runs the configuration/path unit tests. `npm run check` also compiles the Python CLI.

## Repository Layout

```text
skills/tavily/                 # Canonical skill documentation and Python CLI
adapters/pi/extensions/        # Pi resource-discovery adapter
adapters/claude/plugin.json    # Claude Code metadata
adapters/codex/plugin.json     # Codex metadata
adapters/cursor/config.json    # Cursor metadata
```

## License

[MIT](LICENSE)
