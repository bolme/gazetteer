# gazetteer (`gaz`)

Bounded structural queries for huge directory trees — see [DESIGN.md](DESIGN.md).

A gazetteer is a geographic index — compiled once from survey work, then consulted instead of re-surveying. That's the idea here: gaz scan walks your tree once, and everything after reads the index rather than the filesystem. The name holds up as the tool grows, whether it's indexing directories, dataset splits and annotations, or answering an agent over MCP.
Installed as gazetteer, typed as gaz.

## Install

```
uv pip install -e ".[dev]"
```

If that leaves `gaz` raising `ModuleNotFoundError: No module named 'gazetteer'`,
your environment is likely mangling `.pth`-based editable installs. Use the
workaround script instead, which symlinks the package into `site-packages`
directly:

```
./scripts/reinstall-dev.sh
```

## Usage

```
gaz ext [PATH]
gaz tree [PATH]
gaz find PATTERN [PATH]
```

Every command runs under explicit time/count/row budgets and says clearly
when it stopped early. See DESIGN.md for the full contract.
