# Public regression suite

This directory contains the deterministic regression tests that run without private mission logs or account screenshots.

The full local suite also tests recorded UI transitions, OCR crops, crash captures, and Windows DPAPI behavior. Those private fixtures are excluded because they contain account and machine data.

Run the public suite with:

```powershell
python -m pytest
```
