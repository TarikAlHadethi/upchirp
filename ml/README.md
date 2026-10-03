# ml

Classifier on RAD-DAR, PyTorch + MLflow, exported to ONNX. Step 9.

```
python scripts/download_raddar.py   # needs ~/.kaggle/kaggle.json; data goes to data/ (git-ignored)
python ml/train.py                  # ~6 min on a CPU; writes models/ (git-ignored) and docs/reports/classifier.md
```

`ml/report_notes.md` holds the interpretation the report includes. Results and why the rules stay the default: decision 0011.
