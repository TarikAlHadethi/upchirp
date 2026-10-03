"""Download the Real Doppler RAD-DAR dataset from Kaggle into data/raddar/ (step 9).

Needs a Kaggle API token in ~/.kaggle/kaggle.json. The data is never committed:
data/ is git-ignored.

Dataset: https://www.kaggle.com/datasets/iroldan/real-doppler-raddar-database
(Roldan et al., "DopplerNet", IET Radar, Sonar & Navigation, 2020).
"""

from pathlib import Path

DATASET = "iroldan/real-doppler-raddar-database"
OUT = Path(__file__).resolve().parents[1] / "data" / "raddar"


def main() -> None:
    from kaggle.api.kaggle_api_extended import KaggleApi

    api = KaggleApi()
    api.authenticate()
    OUT.mkdir(parents=True, exist_ok=True)
    api.dataset_download_files(DATASET, path=str(OUT), unzip=True, quiet=False)
    files = [p for p in OUT.rglob("*") if p.is_file()]
    print(f"{len(files)} files in {OUT}")


if __name__ == "__main__":
    main()
