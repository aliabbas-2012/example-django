import subprocess
import sys
import time

from django.core.management.base import BaseCommand

from payments.tasks import check_endpoint_health, count_primes_below

N_CPU_TASKS = 8
CPU_N = 500_000  # tuned so one count_primes_below(500_000) call takes ~1s

N_IO_TASKS = 16
IO_URL = "https://httpbin.org/delay/1"  # tuned so one call takes ~1s of network wait


class Command(BaseCommand):
    help = (
        "Runs the SAME two batches -- one CPU-bound, one I/O-bound -- under prefork, "
        "then under gevent, so the difference is about the kind of work, not just a "
        "concurrency number. Starts real Celery workers as subprocesses -- requires "
        "Redis running and internet access for the httpbin calls."
    )

    def handle(self, *args, **options):
        self._run_prefork()
        self._run_gevent()

    def _run_prefork(self):
        self.stdout.write(self.style.MIGRATE_HEADING("prefork --concurrency=4  (4 real OS processes)"))
        worker = subprocess.Popen(
            [
                sys.executable, "-m", "celery", "-A", "config", "worker",
                "--loglevel=warning", "-P", "prefork", "--concurrency=4",
            ],
        )
        try:
            self._wait_for_worker()
            self._run_cpu_bound_batch()
            self._run_io_bound_batch()
        finally:
            worker.terminate()
            worker.wait(timeout=10)
        self.stdout.write("")

    def _run_gevent(self):
        self.stdout.write(self.style.MIGRATE_HEADING("gevent --concurrency=50  (50 green threads, 1 OS process)"))
        worker = subprocess.Popen(
            [
                sys.executable, "-m", "celery", "-A", "config", "worker",
                "--loglevel=warning", "-P", "gevent", "--concurrency=50",
            ],
        )
        try:
            self._wait_for_worker()
            self._run_cpu_bound_batch()
            self._run_io_bound_batch()
        finally:
            worker.terminate()
            worker.wait(timeout=10)
        self.stdout.write("")

    def _run_cpu_bound_batch(self):
        dispatch_start = time.monotonic()
        async_results = [count_primes_below.delay(CPU_N) for _ in range(N_CPU_TASKS)]
        results = [r.get(timeout=60) for r in async_results]
        elapsed = time.monotonic() - dispatch_start
        self.stdout.write(f"  CPU-bound: {N_CPU_TASKS} tasks, ~1s of real computation each -> {elapsed:.2f}s total")
        self._print_finish_times(results, dispatch_start)

    def _run_io_bound_batch(self):
        dispatch_start = time.monotonic()
        async_results = [check_endpoint_health.delay(IO_URL) for _ in range(N_IO_TASKS)]
        results = [r.get(timeout=60) for r in async_results]
        elapsed = time.monotonic() - dispatch_start
        self.stdout.write(f"  I/O-bound: {N_IO_TASKS} tasks, ~1s of network waiting each -> {elapsed:.2f}s total")
        self._print_finish_times(results, dispatch_start)

    def _print_finish_times(self, results, dispatch_start):
        # started_at + elapsed = the moment each task actually finished.
        # Clustered numbers = those tasks ran in parallel/overlapped.
        # Evenly staggered numbers, ~1s apart = they ran one at a time.
        finishes = sorted((r["started_at"] + r["elapsed"]) - dispatch_start for r in results)
        self.stdout.write("    finished at (seconds after dispatch): " + ", ".join(f"{f:.1f}" for f in finishes))

    def _wait_for_worker(self):
        from config.celery import app

        inspector = app.control.inspect(timeout=1)
        for _ in range(60):
            if inspector.ping():
                return
            time.sleep(0.5)
        raise RuntimeError("worker did not come up in time")
