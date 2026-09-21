"""Local fault seams: never exhaust disk space or alter source evidence."""
import errno
import os

class FaultFile:
    def __init__(self, file, mode):
        self.file=file;self.mode=mode;self.fired=False
    def __getattr__(self,name):return getattr(self.file,name)
    def write(self,body):
        if self.fired:raise AssertionError('write retried after failure')
        if self.mode=='disk_full':
            self.fired=True;raise OSError(errno.ENOSPC,'injected')
        if self.mode in ('short','partial'):
            self.fired=True;n=self.file.write(body[:23])
            if self.mode=='partial':raise OSError(errno.EIO,'injected after partial write')
            return n
        return self.file.write(body)
    def flush(self):
        if self.mode=='flush':self.fired=True;raise OSError(errno.EIO,'injected flush')
        return self.file.flush()
    def close(self):return self.file.close()

class FsyncFault:
    def __init__(self,fd):self.fd=fd;self.original=os.fsync;self.calls=0
    def __call__(self,fd):
        if fd==self.fd:
            self.calls+=1;raise OSError(errno.EIO,'injected fsync')
        return self.original(fd)
