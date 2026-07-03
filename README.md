# Fault-Diagnosis-Thesis-Project

This github repository shows the implementation of using dynamic epistemic logic (DEL) in fault diagnosis of a toy example of an electrical circuit. It is an illustration as a part of the thesis project for 'Dynamic Epistemic Logic in Fault Diagnosis in Cyber-Physical Systems'. The results of this DEL implementation is compared to a Bayesian Network baseline model as a shared project, which can be found here: https://github.com/marcusgitz/Thesis-fault-diagnosis-BN. The electrical circuit system and fault scenarios can be found here: https://github.com/kataph/Diagnostic-Assistant-Demo.

To see an overview of how the system works, start with:
```
usage.ipynb
```

## System Structure

```
project/
├── classes.py           # Core data structures
├── loader.py            # YAML parser → EpistemicModel
├── translator.py        # EpistemicModel → KripkeModel (worlds + accessibility)
├── announcer.py         # Public Announcement Logic (PAL) world pruning
├── main.py              # CLI 
├── circuit.yaml         # Circuit definition (nodes, faults, scenarios)
└── README.md            # This file
```

## Installation

### Requirements
- Python 3.9+
- `pyyaml`

### Setup

```bash
pip install pyyaml
```

Clone or download the repository:

```bash
cd /path/to/Fault-Diagnosis-Thesis-Individual
```

## Usage

### 1. Command-Line Interface (CLI)

**Interactive menu** (recommended for exploration):
```bash
python main.py
```
You'll see a table of all scenarios and can pick one by ID.

**Run a specific scenario:**
```bash
python main.py --scenario 14
```

**Run all scenarios:**
```bash
python main.py --all
```

**Use a different circuit file:**
```bash
python main.py --yaml path/to/other_circuit.yaml
```

**Skip observability validation** (for testing):
```bash
python main.py --no-validate
```

### 2. Jupyter Notebook

In a Jupyter notebook, import the modules directly:

```python
from loader import load_circuit
from translator import build_kripke_model, AxiomEngine
from announcer import AnnouncementProcessor

# Load the circuit
model, scenarios = load_circuit("circuit.yaml")

# Pick a scenario
scenario = next(s for s in scenarios if s.id == 14)

# Build the Kripke model
kripke = build_kripke_model(model, include_all_ok=False)
engine = AxiomEngine(model)

# Run announcements
processor = AnnouncementProcessor(kripke, engine, scenario, validate=True)
results = processor.run()

# Inspect results
for r in results:
    print(r.summary())

# Check final diagnosis
final = results[-1]
print(f"Resolved: {final.is_resolved}")
print(f"Surviving faults: {final.surviving_faults}")
```
### 3. Programmatic Use

```python
from main import run_scenario

results = run_scenario(scenario, "circuit.yaml", validate=True)
```
## Output Format

When you run a scenario, the system prints:

1. **Header** — scenario ID, agent name, tools, initial world count
2. **Per-step blocks** — for each announcement:
   - Observations announced
   - Worlds before/after pruning
   - Pruned world names
   - Intermediate diagnosis status (✓ resolved, ? ambiguous, ⚠ contradiction)
3. **Final diagnosis** — one of the following possibilities:
   - Suspected faulty component(s)
   - Model Contradiction: all worlds pruned by announcements


Example:

```
Step 1:
  Observations:
    O_PSU_LED = on/12V/high (normal)
    O_Ind_1 = on/12V/high (normal)
    O_Ind_2 = on/12V/high (normal)
    M_battery = on/12V/high (normal)
    M_PSU_short = on/12V/high (normal)
  Worlds: 20 → 14 (6 pruned)
  Remaining candidates: ['F_cable_3', 'F_cable_4', 'F_cable_5', 'F_cable_6', 'F_cable_7', 'F_cable_8', 'F_cable_load', 'F_sw_3', 'F_sw_4', 'F_sw_5', 'F_sw_6', 'F_sw_7', 'F_sw_8', 'F_lamp']

Step 2:
  Observations:
    O_Ind_3 = off/0V/low (faulty)
    O_Ind_4 = off/0V/low (faulty)
    O_Ind_5 = off/0V/low (faulty)
    O_Ind_6 = off/0V/low (faulty)
    O_Ind_7 = off/0V/low (faulty)
    O_Ind_8 = off/0V/low (faulty)
  Worlds: 14 → 2 (12 pruned)
  Remaining candidates: ['F_cable_3', 'F_sw_3']

Step 3:
  Observations:
    O_Lamp = off/0V/low (faulty)
    O_Lamp_indicator = off/0V/low (faulty)
  Worlds: 2 → 2 (0 pruned)
  Remaining candidates: ['F_cable_3', 'F_sw_3']
```

## Example Scenarios

### Scenario 7: Battery exhausted
- **Observations**: PSU LED on, indicator off, main lamp off
- **Expected diagnosis**: `F_battery`
- **Key insight**: If the PSU is working but no voltage reaches the lamp, the battery must be exhausted.

### Scenario 14: PSU short
- **Observations**: PSU LED on, indicator on, multimeter reads low resistance
- **Expected diagnosis**: `F_PSU_short`
- **Key insight**: A low-resistance reading at the PSU confirms a short. The indicator is on because voltage is present (battery is good).

### Scenario 11: Lamp broken
- **Observations**: PSU LED on, indicator off, main lamp off
- **Expected diagnosis**: Cannot resolve (ambiguous)
- **Key insight**: Without a multimeter, the technician cannot distinguish between a broken lamp and a broken upstream component. Both would produce the same observations.

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `ModuleNotFoundError: yaml` | PyYAML not installed | `pip install pyyaml` |
| `FileNotFoundError: circuit.yaml` | File not in current directory | Use `--yaml path/to/file` or `cd` to the right directory |
| `ValueError: Agent X cannot observe Y` | Scenario observation references an unobservable node | Check agent's `observes:` list in `circuit.yaml`, or use `--no-validate` |
| `ValueError: Each possible_dependency entry must have...` | YAML indentation error in `possible_dependencies:` block | Ensure 2-space indentation; use `-` only on the first field of each entry |
| `CONTRADICTION: no worlds survive` | All worlds pruned by announcements | Check scenario observations for inconsistencies with the circuit model |



