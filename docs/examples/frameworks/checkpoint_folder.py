"""Point a framework at the checkpoint folder. The guide compiles this file and does not run it: it needs the frameworks."""
from kaos_lib import checkpoint


def ultralytics():
    from ultralytics import YOLO
    YOLO("yolo11n.pt").train(project=str(checkpoint.dir()), name="run", exist_ok=True)


def lightning():
    import pytorch_lightning as pl
    from pytorch_lightning.callbacks import ModelCheckpoint
    return pl.Trainer(callbacks=[ModelCheckpoint(dirpath=checkpoint.dir(), save_last=True)])


def hugging_face():
    from transformers import TrainingArguments
    return TrainingArguments(output_dir=str(checkpoint.dir()), save_steps=500)
