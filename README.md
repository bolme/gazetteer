# gazetteer (`gaz`)

Bounded structural queries for huge directory trees — see [DESIGN.md](DESIGN.md).

## Install

```
uv pip install -e ".[dev]"
```

## Usage

```
gaz ext [PATH]
gaz tree [PATH]
gaz find PATTERN [PATH]
```

Every command runs under explicit time/count/row budgets and says clearly
when it stopped early. See DESIGN.md for the full contract.
