import asyncio
from time import time

from dask_jobqueue import PBSJob, SGEJob, SLURMJob, LSFJob, LocalJob, LocalCluster
from dask_jobqueue.job import JobQueueCluster
from dask.distributed import Scheduler, Client

import pytest


def test_basic():
    job = PBSJob(scheduler="127.0.0.1:12345", cores=1, memory="1 GB")
    assert "127.0.0.1:12345" in job.job_script()


job_params = [
    pytest.param(SGEJob, marks=[pytest.mark.env("sge")]),
    pytest.param(PBSJob, marks=[pytest.mark.env("pbs")]),
    pytest.param(SLURMJob, marks=[pytest.mark.env("slurm")]),
    pytest.param(LSFJob, marks=[pytest.mark.env("lsf")]),
    LocalJob,
]


@pytest.mark.parametrize("Job", job_params)
@pytest.mark.asyncio
async def test_job(Job):
    async with Scheduler(port=0) as s:
        print(1)
        job = Job(scheduler=s.address, name="foo", cores=1, memory="1GB")
        print(2)
        job = await job
        print(3)
        async with Client(s.address, asynchronous=True) as client:
            print(4)
            await client.wait_for_workers(1)
            print(5)
            assert list(s.workers.values())[0].name == "foo"

        print(6)
        await job.close()
        print(7)

        start = time()
        while len(s.workers):
            await asyncio.sleep(0.1)
            assert time() < start + 10
        print(8)


@pytest.mark.parametrize("Job", job_params)
@pytest.mark.asyncio
async def test_cluster(Job):
    async with JobQueueCluster(
        1, cores=1, memory="1GB", Job=Job, asynchronous=True, name="foo"
    ) as cluster:
        async with Client(cluster, asynchronous=True) as client:
            assert len(cluster.workers) == 1
            cluster.scale(2)
            await cluster
            assert len(cluster.workers) == 2
            assert all(isinstance(w, Job) for w in cluster.workers.values())
            assert all(w.status == "running" for w in cluster.workers.values())
            await client.wait_for_workers(2)

            cluster.scale(1)
            start = time()
            await cluster
            while len(cluster.scheduler.workers) > 1:
                await asyncio.sleep(0.1)
                assert time() < start + 10


@pytest.mark.parametrize("Job", job_params)
@pytest.mark.asyncio
async def test_adapt(Job):
    async with JobQueueCluster(
        1, cores=1, memory="1GB", Job=Job, asynchronous=True, name="foo"
    ) as cluster:
        async with Client(cluster, asynchronous=True) as client:
            await client.wait_for_workers(1)
            cluster.adapt(minimum=0, maximum=4, interval="10ms")

            start = time()
            while len(cluster.scheduler.workers) or cluster.workers:
                await asyncio.sleep(0.050)
                assert time() < start + 10
            assert not cluster.worker_spec
            assert not cluster.workers

            future = client.submit(lambda: 0)
            await client.wait_for_workers(1)

            del future

            start = time()
            while len(cluster.scheduler.workers) or cluster.workers:
                await asyncio.sleep(0.050)
                assert time() < start + 10
            assert not cluster.worker_spec
            assert not cluster.workers


def test_header_lines_skip():
    job = PBSJob(cores=1, memory="1GB", job_name="foobar")
    assert "foobar" in job.job_script()

    job = PBSJob(cores=1, memory="1GB", job_name="foobar", header_skip=["-N"])
    assert "foobar" not in job.job_script()


@pytest.mark.asyncio
async def test_nprocs():
    async with LocalCluster(
        cores=2, memory="4GB", processes=2, asynchronous=True
    ) as cluster:
        s = cluster.scheduler
        async with Client(cluster, asynchronous=True) as client:
            cluster.scale(cores=2)
            await cluster
            await client.wait_for_workers(2)
            assert len(cluster.workers) == 1  # two workers, one job
            assert len(s.workers) == 2
            assert cluster.plan == {ws.name for ws in s.workers.values()}

            cluster.scale(cores=1)
            await cluster
            await asyncio.sleep(0.2)
            assert len(cluster.scheduler.workers) == 2  # they're still one group
