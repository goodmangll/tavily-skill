# Tavily Skill

A Python 3, standard-library-only skill for Tavily web search, URL extraction, site mapping,
crawling, and deep research. The shared source of truth is [`skills/tavily/`](skills/tavily/).

## Support Matrix

| Platform | Status | Files | Installation or validation |
|---|---|---|---|
| [Pi](https://pi.dev) | Supported | `package.json` with `pi.skills` | `pi install git:github.com/goodmangll/tavily-skill` |
| Claude Code | Supported | `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` | `claude plugin marketplace add goodmangll/tavily-skill`, then `claude plugin install tavily-skill@tavily-skill` |
| Codex | Manifest included | `.codex-plugin/plugin.json` | Validate the current marketplace or plugin-browser installation flow before publishing a direct install command. |
| Cursor | Not configured | None | Add support only after verifying its current official plugin format and end-to-end installation flow. |

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

| Purpose | Default location |
|---|---|
| User configuration | `${XDG_CONFIG_HOME:-~/.config}/tavily/config.yaml` |
| Runtime state | `${XDG_STATE_HOME:-~/.local/state}/tavily/state.json` |
| Results | `${XDG_DATA_HOME:-~/.local/share}/tavily/results/` |

Keep `config.yaml` outside this repository. It contains API credentials.

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
claude plugin validate .
```

Tests cover the YAML/XDG configuration behavior and platform manifest layout. Before documenting a
new host installation path, validate it end-to-end in that host and update the support matrix.

## Repository Layout

```text
skills/tavily/                 # Canonical skill documentation and Python CLI
.claude-plugin/                # Claude Code plugin and marketplace metadata
.codex-plugin/                 # Codex plugin metadata
package.json                   # Pi package metadata
```

## License

[MIT](LICENSE)
