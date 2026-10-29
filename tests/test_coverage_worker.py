"""Coverage subprocess output, Stop and lifetime bounds; no SQL or providers."""
import asyncio
import sys
import signal
import time
from unittest.mock import patch
import pytest
from app.collection import coverage_worker as worker


@pytest.mark.parametrize('mode',['success','stop','overflow','deadline'])
def test_worker_owns_child_until_exit(tmp_path,mode):
    asyncio.run(exercise(tmp_path,mode))


async def exercise(tmp_path,mode):
    launch=asyncio.create_subprocess_exec;children=[]
    code={'success':'print(\'{"published": true, "provider_requests": 0}\')',
          'stop':'import time; time.sleep(30)',
          'overflow':'import sys,time; sys.stdout.write("x"*131072); sys.stdout.flush(); time.sleep(30)',
          'deadline':'import time; time.sleep(30)'}[mode]
    async def start(*args,**kwargs):
        p=await launch(sys.executable,'-c',code,**kwargs);children.append(p);return p
    stop=lambda:mode=='stop' and bool(children)
    with patch.object(worker.asyncio,'create_subprocess_exec',side_effect=start), \
         patch.object(worker,'MAX_SECONDS',.2), \
         patch.object(worker,'MAX_REPLY_BYTES',1024):
        if mode in ('overflow','deadline'):
            with pytest.raises(ValueError,match='coverage_worker_(reply_capacity|deadline)'):
                await worker.run(stop,root=tmp_path)
        else:
            result=await worker.run(stop,root=tmp_path)
            assert result.get('published') is (mode=='success')
    assert children and all(p.returncode is not None for p in children)


@pytest.mark.parametrize('mode',['transient','persistent','stop_during_pressure'])
def test_pressure_grace_keeps_stop_deadline_and_child_ownership(tmp_path,mode):
    async def exercise_pressure():
        from app.collection.background_work import BACKGROUND
        launch=asyncio.create_subprocess_exec;children=[];started=time.monotonic()
        code='import time; time.sleep(.06); print(\'{"published": true}\')' if mode=='transient' else 'import time; time.sleep(30)'
        async def start(*args,**kwargs):
            p=await launch(sys.executable,'-c',code,**kwargs);children.append(p);return p
        pressure=lambda:mode!='transient' or time.monotonic()-started<.04
        stop=lambda:mode=='stop_during_pressure' and time.monotonic()-started>.02
        with patch.object(worker.asyncio,'create_subprocess_exec',side_effect=start), \
                patch.object(worker,'MAX_SECONDS',.3), \
                patch.object(BACKGROUND,'critical_acquisition_pressure',side_effect=pressure):
            if mode=='persistent':
                with pytest.raises(ValueError,match='coverage_worker_deadline'):await worker.run(stop,root=tmp_path)
            else:
                result=await worker.run(stop,root=tmp_path)
                assert result.get('published') is (mode=='transient')
        assert children and all(p.returncode is not None for p in children)
    asyncio.run(exercise_pressure())


def test_component_progress_survives_pressure_cancellation(tmp_path):
    async def exercise_progress():
        from app.collection.background_work import BACKGROUND,AcquisitionDeferred
        launch=asyncio.create_subprocess_exec;children=[];cursor={}
        code='import time; print(\'{"worker_progress":{"estimates_cursor":7,"estimates_after":"completed"}}\',flush=True); time.sleep(30)'
        async def start(*args,**kwargs):
            p=await launch(sys.executable,'-c',code,**kwargs);children.append(p);return p
        with patch.object(worker.asyncio,'create_subprocess_exec',side_effect=start), \
             patch.object(BACKGROUND,'critical_acquisition_pressure',side_effect=lambda:bool(cursor)):
            with pytest.raises(AcquisitionDeferred):
                await worker.run(lambda:False,root=tmp_path,module='app.collection.financial_worker',on_progress=cursor.update)
        assert cursor==dict(estimates_cursor=7,estimates_after='completed')
        assert children and all(p.returncode is not None for p in children)
    asyncio.run(exercise_progress())


@pytest.mark.skipif(not hasattr(signal,'SIGSTOP'),reason='POSIX child suspension')
def test_coverage_pauses_cpu_work_then_resumes_same_census(tmp_path):
    async def exercise_pause():
        from app.collection.background_work import BACKGROUND
        launch=asyncio.create_subprocess_exec;children=[];pressure=[False]
        progress=tmp_path/'progress'
        code=f'''import time
from pathlib import Path
p=Path({str(progress)!r})
for i in range(80):
 p.write_text(str(i));time.sleep(.01)
print('{{"published":true}}')
'''
        async def start(*args,**kwargs):
            p=await launch(sys.executable,'-c',code,**kwargs);children.append(p);return p
        with patch.object(worker.asyncio,'create_subprocess_exec',side_effect=start), \
             patch.object(BACKGROUND,'critical_acquisition_pressure',side_effect=lambda:pressure[0]), \
             patch.object(worker,'MAX_SECONDS',5):
            task=asyncio.create_task(worker.run(lambda:False,root=tmp_path))
            try:
                for _ in range(100):
                    if progress.exists():break
                    await asyncio.sleep(.01)
                assert progress.exists()
                pressure[0]=True
                await asyncio.sleep(.2)
                frozen=progress.read_text()
                await asyncio.sleep(.15)
                assert progress.read_text()==frozen
                pressure[0]=False
                result=await task
                assert result['published'] and result['worker_pauses']==1
                assert result['worker_paused_seconds']>=.15
                assert progress.read_text()=='79'
            finally:
                pressure[0]=False
                if not task.done():task.cancel()
                await asyncio.gather(task,return_exceptions=True)
        assert len(children)==1 and children[0].returncode==0
    asyncio.run(exercise_pause())


@pytest.mark.parametrize('mode',['clears','stop','persistent'])
def test_coverage_admission_wait_is_bounded_and_starts_only_when_clear(tmp_path,mode):
    async def exercise_admission():
        from app.collection.background_work import BACKGROUND,AcquisitionDeferred
        launch=asyncio.create_subprocess_exec;children=[];started=time.monotonic()
        pressure=lambda:mode!='clears' or time.monotonic()-started<.08
        async def start(*args,**kwargs):
            assert not pressure()
            p=await launch(sys.executable,'-c','print(\'{"published":true}\')',**kwargs);children.append(p);return p
        stop=lambda:mode=='stop' and time.monotonic()-started>.02
        with patch.object(worker.asyncio,'create_subprocess_exec',side_effect=start), \
             patch.object(BACKGROUND,'acquisition_pressure',side_effect=pressure), \
             patch.object(worker,'MAX_SECONDS',.3):
            if mode=='persistent':
                with pytest.raises(AcquisitionDeferred):await worker.run(stop,root=tmp_path)
            else:
                result=await worker.run(stop,root=tmp_path)
                assert result.get('published') is (mode=='clears')
        assert len(children)==(1 if mode=='clears' else 0)
        assert all(p.returncode is not None for p in children)
    asyncio.run(exercise_admission())


@pytest.mark.parametrize('module_name',['coverage_worker','financial_worker'])
def test_child_failure_preserves_safe_locations(module_name,tmp_path,capsys):
    import importlib
    import json
    from app.storage import store
    module=importlib.import_module('app.collection.'+module_name)
    from app.collection.background_work import BACKGROUND
    with patch.object(sys,'argv',[module_name,str(tmp_path),str(module.os.getppid()),'{}']), \
         patch.object(store,'ROOT',tmp_path), \
         patch.object(BACKGROUND,'limit',BACKGROUND.limit), \
         patch.object(BACKGROUND,'runway',BACKGROUND.runway), \
         patch.object(store,'connect',side_effect=OSError('SECRET database payload')):
        module.main()
    wire=capsys.readouterr().out
    result=json.loads(wire)
    assert result['worker_error']==module_name+'_failed'
    assert result['worker_failure']['exception']=='OSError'
    assert any(module_name+'.py' in f for f in result['worker_failure']['frames'])
    assert 'SECRET' not in wire


def test_parent_logs_child_failure_without_public_message(tmp_path,caplog):
    async def exercise():
        launch=asyncio.create_subprocess_exec
        code='print(\'{"worker_error":"SECRET", "worker_failure":{"exception":"OSError","frames":["worker.py:12:run"]}}\')'
        async def start(*args,**kwargs):return await launch(sys.executable,'-c',code,**kwargs)
        with patch.object(worker.asyncio,'create_subprocess_exec',side_effect=start):
            with pytest.raises(ValueError,match='^coverage_worker_failed$'):
                await worker.run(lambda:False,root=tmp_path)
    asyncio.run(exercise())
    assert 'worker.py:12:run' in caplog.text
    assert 'SECRET' not in caplog.text


def test_repeated_cancellation_joins_cleanup(tmp_path):
    async def exercise():
        launch=asyncio.create_subprocess_exec
        entered=asyncio.Event();release=asyncio.Event();children=[]
        async def start(*args,**kwargs):
            p=await launch(sys.executable,'-c','import time; time.sleep(30)',**kwargs)
            children.append(p)
            original=p.wait
            async def wait():
                entered.set();await release.wait();return await original()
            p.wait=wait
            return p
        with patch.object(worker.asyncio,'create_subprocess_exec',side_effect=start):
            task=asyncio.create_task(worker.run(lambda:False,root=tmp_path))
            while not children:await asyncio.sleep(.01)
            task.cancel();await asyncio.wait_for(entered.wait(),2)
            task.cancel();await asyncio.sleep(.01)
            assert not task.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):await task
        assert children[0].returncode is not None
    asyncio.run(exercise())


def test_cancelled_owned_thread_failure_is_observable(caplog):
    import threading
    from app.collection.bulk_checkpoint import owned_thread
    async def exercise():
        entered=threading.Event();release=threading.Event()
        def work():
            entered.set();release.wait(2);raise OSError('SECRET persisted write')
        task=asyncio.create_task(owned_thread(work))
        while not entered.is_set():await asyncio.sleep(.01)
        task.cancel();await asyncio.sleep(.01);release.set()
        with pytest.raises(asyncio.CancelledError):await task
    asyncio.run(exercise())
    assert 'owned_thread_after_cancellation' in caplog.text
    assert 'OSError' in caplog.text and 'SECRET' not in caplog.text


def test_cleanup_failure_preserves_cancellation_and_safe_log(tmp_path,caplog):
    async def exercise():
        launch=asyncio.create_subprocess_exec;children=[]
        async def start(*args,**kwargs):
            p=await launch(sys.executable,'-c','import time; time.sleep(30)',**kwargs)
            original=p.wait
            async def wait():
                await original()
                raise OSError('SECRET cleanup')
            p.wait=wait;children.append(p);return p
        with patch.object(worker.asyncio,'create_subprocess_exec',side_effect=start):
            task=asyncio.create_task(worker.run(lambda:False,root=tmp_path))
            while not children:await asyncio.sleep(.01)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):await task
        assert children[0].returncode is not None
    asyncio.run(exercise())
    assert 'calculation_worker_cleanup' in caplog.text
    assert 'SECRET' not in caplog.text


def test_shared_thread_policy_preserves_results_kwargs_and_original_errors():
    from app.owned_work import joined_thread
    async def exercise():
        expected=object()
        assert await joined_thread(__name__,'test_failure',lambda *, value:value,value=expected) is expected
        original=OSError('authored error')
        def fail():raise original
        with pytest.raises(OSError) as caught:
            await joined_thread(__name__,'test_failure',fail)
        assert caught.value is original
    asyncio.run(exercise())
