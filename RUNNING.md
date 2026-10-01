# Running Wardrobe-AI

Two terminals. That is the whole thing.

## 1. Backend

**Mac**
```
cd ~/Desktop/wardrobe-ai
./ai_env312/bin/python -m backend.app
```

**Windows** (PowerShell blocks `activate.bat`, so call the interpreter
directly — this is the command that works)
```
cd C:\Users\ADMIN\wardrobe-ai
.\ai_env\Scripts\python.exe -m backend.app
```

It serves on **http://localhost:5001**. On start it prints a short
configuration summary — database host, image storage, weather, email,
virtual try-on — with no secret values in it. If something is not
configured it says so there.

## 2. Frontend

```
cd frontend
npm start          # Windows: npm.cmd start
```

Opens **http://localhost:3000** and talks to the backend on 5001.

## Before a demo — the thirty-second check

```
python -m backend.check_setup
```

Every line green means the database, storage, weather, email and
try-on are all reachable from this machine.

## Checking it really works, end to end

`backend/tests/smoke_run.py` starts the backend, registers two
throwaway accounts, uploads eight garment photos through the real
pipeline, checks the wardrobe, recommendations, account isolation and
the try-on routes, then deletes everything it created.

It refuses to run unless `MONGODB_DB_NAME` contains "test", and refuses
an Atlas connection string outright, so it cannot touch the real
wardrobe. Point it at any local MongoDB:

```
MONGODB_URI=mongodb://127.0.0.1:27017 \
MONGODB_DB_NAME=wardrobe_smoketest \
python -m backend.tests.smoke_run
```

## The test suites

```
python -m unittest discover -s backend/tests -t .     # 335 tests
cd frontend && npm test -- --watchAll=false           # 61 tests
cd frontend && npm run build                          # production build
```

## Optional, but worth it

**Better background removal.** Without `rembg` the app falls back to
OpenCV, which is measurably worse on hard photos (mean IoU 0.949 vs
0.970, and a far rougher worst case — see
`docs/UPLOAD_AND_TRYON_ACCURACY.md`):

```
pip install rembg onnxruntime
```

The first upload afterwards downloads a ~170 MB model once.

**Similar-clothes search** needs TensorFlow. Without it the rest of the
app runs normally and that one page reports itself unavailable:

```
pip install tensorflow
```

**More try-on capacity.** The public Hugging Face Space gives the whole
application only a few GPU-minutes a day. For a demo, start
`spaces/tryon/kaggle_tryon.ipynb` on Kaggle and put the link it prints
into `TRYON_FALLBACK_URL` — see
`docs/VIRTUAL_TRYON_COST_AND_PROVIDER.md`.
