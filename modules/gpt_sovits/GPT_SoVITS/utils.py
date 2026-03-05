"""Minimal utils module — required for torch.load() to unpickle checkpoints
that were saved with references to utils.HParams."""

import json


class HParams:
    """Hyper-parameters container (used in saved checkpoints)."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            if type(v) == dict:
                v = HParams(**v)
            self[k] = v

    def keys(self):
        return self.__dict__.keys()

    def items(self):
        return self.__dict__.items()

    def values(self):
        return self.__dict__.values()

    def __len__(self):
        return len(self.__dict__)

    def __getitem__(self, key):
        return getattr(self, key)

    def __setitem__(self, key, value):
        setattr(self, key, value)

    def __contains__(self, key):
        return key in self.__dict__

    def __repr__(self):
        return self.__dict__.__repr__()

    def get(self, key, default=None):
        return self.__dict__.get(key, default)


def get_hparams_from_file(config_path):
    with open(config_path, "r", encoding="utf-8") as f:
        data = f.read()
    config = json.loads(data)
    hparams = HParams(**config)
    return hparams
