"""Bounded cache of verified saved projections; any filesystem change invalidates."""
from collections import OrderedDict
from copy import deepcopy
import json

class SavedSnapshotCache:
    def __init__(self,maximum_bytes=16*1024*1024):
        self.maximum_bytes=maximum_bytes;self.entries=OrderedDict();self.size=0

    def load(self,folder,loader):
        key=str(folder.resolve())
        signature=[]
        for p in sorted(folder.rglob('*')):
            stat=p.lstat()
            signature.append((str(p.relative_to(folder)),stat.st_ino,stat.st_mode,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns))
        old=self.entries.pop(key,None)
        if old:
            self.size-=old[2]
            if signature==old[0]:
                self.entries[key]=old;self.size+=old[2];return deepcopy(old[1])
        snapshot=loader(folder)
        size=len(json.dumps(snapshot,default=str).encode())
        if size<=self.maximum_bytes:
            while self.entries and (self.size+size>self.maximum_bytes or len(self.entries)>=8):
                _,entry=self.entries.popitem(last=False);self.size-=entry[2]
            self.entries[key]=(signature,deepcopy(snapshot),size);self.size+=size
        return snapshot
