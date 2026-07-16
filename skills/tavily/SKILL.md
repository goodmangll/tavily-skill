---
name: tavily
description: >-
  Search the web, extract URL content, map and crawl websites, or run deep research through the
  Tavily API. Use when the user asks for current web information, news, URL extraction, site
  discovery, crawling, or a research report. Results are written to disk by default; use --stdout
  when the full payload is needed inline.
---

# Tavily

Use the bundled `tavily.py` CLI for real-time web access through the Tavily REST API. It supports
`search`, `extract`, `map`, `crawl`, and `research`.

## When To Use

Use this skill for:

- Searching the web or checking current news and information
- Extracting content from one or more URLs
- Discovering a website's URL structure
- Crawling a website for relevant content
- Producing a deep research report

## Configuration

The CLI follows the XDG Base Directory specification. Create the configuration file at:

```text
${XDG_CONFIG_HOME:-~/.config}/tavily/config.yaml
```

```yaml
api_keys:
  - tvly-dev-xxx1
  - tvly-dev-xxx2

# Optional: override the directory for generated result JSON.
# output_dir: ~/.local/share/tavily/results
```

| Purpose | Default path |
|---|---|
| User configuration | `${XDG_CONFIG_HOME:-~/.config}/tavily/config.yaml` |
| Runtime state | `${XDG_STATE_HOME:-~/.local/state}/tavily/state.json` |
| Generated results | `${XDG_DATA_HOME:-~/.local/share}/tavily/results/` |

Get an API key from https://tavily.com.

## Usage

Run `python3 tavily.py` from this skill's directory.

### Search

```bash
python3 tavily.py search "latest AI news"
python3 tavily.py search "openai releases" --max-results 10 --search-depth advanced --topic news
python3 tavily.py search "agent framework" --include-domain github.com --include-domain docs.anthropic.com
python3 tavily.py search "election results" --time-range week
```

### Extract

```bash
python3 tavily.py extract https://example.com
python3 tavily.py extract https://example.com https://example.org
python3 tavily.py extract https://en.wikipedia.org/wiki/AI --query "AI history" --extract-depth advanced
```

### Map And Crawl

```bash
python3 tavily.py map --url docs.tavily.com --max-depth 3 --limit 100
python3 tavily.py crawl --url docs.tavily.com --instructions "find Python SDK pages" --extract-depth advanced
```

### Research

```bash
python3 tavily.py research create --input "What are the latest developments in AI?"
python3 tavily.py research create --input "AI regulation trends" --model pro --output-length long --wait
python3 tavily.py research get --request-id 123e4567-...
```

## Output

By default, `search`, `extract`, `map`, and `crawl` write a complete JSON payload to the results
directory and print a compact JSON status to stdout. Use `--stdout` to print the full payload
instead, or `--output <path>` to choose a destination.

For `research create --wait`, the completed report is printed to stdout.

## Notes

- Prefer the default file output for large responses and read the output path when details are needed.
- Treat LLM-generated summary fields as a starting point, not a source of record.
- `HTTP 401` or `403` means an API key is invalid or revoked.
- `HTTP 429` means Tavily is rate limiting the request; wait and retry.
