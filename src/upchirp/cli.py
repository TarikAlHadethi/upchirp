"""Upchirp command line."""

import os
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from upchirp.config import ArrayConfig, ChirpConfig
from upchirp.dsp.detect import Detection
from upchirp.dsp.tracker import TrackState
from upchirp.frame import Frame
from upchirp.pipeline import FrameResult
from upchirp.recording import (
    DETECTIONS_FILE,
    TRACKS_FILE,
    has_ground_truth,
    read_ground_truth,
    read_manifest,
    read_rows,
    record_simulation,
    resolve_session,
)
from upchirp.replay import process_session
from upchirp.scoring import format_report, score_detections, score_tracks
from upchirp.sim.engine import Simulator
from upchirp.sim.scene import get_scene
from upchirp.sources.replay import ReplaySource

app = typer.Typer(help="Upchirp command line", no_args_is_help=True)


def _load_dotenv(path: Path = Path(".env")) -> None:
    """KEY=VALUE lines from a git-ignored .env; real environment variables win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#") and value:
            os.environ.setdefault(key.strip(), value.strip().strip('"'))


_load_dotenv()

DEFAULT_DATA_DIR = Path(os.environ.get("UPCHIRP_DATA_DIR", "data"))
DataDir = Annotated[Path, typer.Option(help="Where sessions are saved")]


@app.command()
def sim(
    scene: Annotated[str, typer.Option(help="Scene name")] = "default",
    seed: Annotated[int, typer.Option(help="Noise seed; the same seed gives the same data")] = 0,
    notes: Annotated[str, typer.Option(help="Operator notes stored with the recording")] = "",
    data_dir: DataDir = DEFAULT_DATA_DIR,
) -> None:
    """Generate a simulated scene and save its frames and ground truth."""
    try:
        scene_def = get_scene(scene)
    except ValueError as e:
        raise typer.BadParameter(str(e), param_hint="--scene") from None
    now = datetime.now(UTC)
    session_id = f"sim-{scene}-{now:%Y%m%dT%H%M%S}{now.microsecond // 1000:03d}Z"
    simulator = Simulator(
        scene_def, session_id=session_id, start_ns=time.time_ns(), seed=seed,
        chirp=ChirpConfig(), array=ArrayConfig(),
    )
    session_dir = record_simulation(simulator, data_dir, notes)
    truth = read_ground_truth(session_dir)
    typer.echo(f"Saved {scene_def.n_frames} frames and {len(truth)} ground truth rows")
    typer.echo(f"Session: {session_id}")
    typer.echo(f"Path:    {session_dir}")


@app.command()
def replay(
    session: Annotated[str, typer.Option(help="Session id, or 'latest'")] = "latest",
    realtime: Annotated[bool, typer.Option(help="Pace frames at their recorded rate")] = False,
    every: Annotated[int, typer.Option(min=1, help="Print tracks every N frames")] = 10,
    data_dir: DataDir = DEFAULT_DATA_DIR,
) -> None:
    """Replay a recording through the pipeline and save its detections and tracks."""
    try:
        session_dir = resolve_session(data_dir, session)
    except FileNotFoundError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from None
    manifest = read_manifest(session_dir)
    typer.echo(f"Replaying {manifest['session_id']} ({manifest['n_frames']} frames)")
    first_ns: list[int] = []

    def show(result: FrameResult) -> None:
        frame = result.frame
        first_ns.append(frame.timestamp_ns)
        if frame.frame_index % every:
            return
        confirmed = [t for t in result.tracks if t.confirmed]
        t = (frame.timestamp_ns - first_ns[0]) / 1e9
        typer.echo(f"t={t:5.1f}s  {len(result.detections)} detections, {len(confirmed)} tracks")
        for trk in confirmed:
            typer.echo(f"    track {trk.track_id:>3}  {trk.label:<10}  range {trk.range_m:5.1f} m  "
                       f"azimuth {trk.azimuth_deg:+6.1f} deg  speed {trk.speed_mps:4.1f} m/s")

    summary = process_session(session_dir, realtime=realtime, on_frame=show)
    n, secs = summary["frames"], max(summary["seconds"], 1e-6)
    typer.echo(f"Replayed {n} frames in {secs:.2f} s ({n / secs:.0f} frames/s): "
               f"{summary['detections']} detections, "
               f"{summary['confirmed_tracks']} confirmed tracks")
    if has_ground_truth(session_dir):
        typer.echo("Run 'upchirp score' to compare with ground truth.")


@app.command()
def score(
    session: Annotated[str, typer.Option(help="Session id, or 'latest'")] = "latest",
    data_dir: DataDir = DEFAULT_DATA_DIR,
) -> None:
    """Score a replayed session's detections and tracks against its ground truth."""
    try:
        session_dir = resolve_session(data_dir, session)
    except FileNotFoundError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from None
    if not has_ground_truth(session_dir):
        typer.echo("This session has no ground truth (only simulated sessions do).", err=True)
        raise typer.Exit(code=1)
    if not (session_dir / TRACKS_FILE).exists():
        typer.echo("No pipeline output yet; run 'upchirp replay' first.", err=True)
        raise typer.Exit(code=1)
    chirp = ChirpConfig(**read_manifest(session_dir)["chirp_config"])
    truth = read_ground_truth(session_dir)
    det_score = score_detections(read_rows(session_dir / DETECTIONS_FILE, Detection), truth, chirp)
    trk_score = score_tracks(read_rows(session_dir / TRACKS_FILE, TrackState), truth)
    typer.echo(format_report(det_score, trk_score))


@app.command()
def ask(
    question: Annotated[str, typer.Argument(help="Question about what the radar saw")],
    data_dir: DataDir = DEFAULT_DATA_DIR,
) -> None:
    """Ask the agent a question. Settings changes wait for your yes."""
    import asyncio

    from upchirp.agent.graph import ask as ask_agent

    def approver(calls: list[dict[str, object]]) -> bool:
        for call in calls:
            typer.echo(f"The agent wants to run {call['name']} with {call['args']}")
        return typer.confirm("Allow it?", default=False)

    answer, _ = asyncio.run(ask_agent(question, data_dir, approver))
    typer.echo(answer)


@app.command()
def mcp(data_dir: DataDir = DEFAULT_DATA_DIR) -> None:
    """Run the MCP server on stdio, for any MCP client (Claude Desktop, Claude Code)."""
    os.environ["UPCHIRP_DATA_DIR"] = str(data_dir.resolve())
    from upchirp.agent.server import build_server

    build_server().run()


DEV_DATABASE_URL = "postgresql://upchirp:upchirp-dev-only@127.0.0.1:5433/upchirp"


def _paced(frames: Iterator[Frame], realtime: bool) -> Iterator[Frame]:
    """Release frames at their recorded rate (by timestamp) when realtime is on."""
    start_wall = time.monotonic()
    first_ns: int | None = None
    for frame in frames:
        if realtime:
            first_ns = frame.timestamp_ns if first_ns is None else first_ns
            delay = (frame.timestamp_ns - first_ns) / 1e9 - (time.monotonic() - start_wall)
            if delay > 0:
                time.sleep(delay)
        yield frame


@app.command()
def source(
    session: Annotated[str, typer.Option(help="Recording to replay, or 'latest'")] = "latest",
    scene: Annotated[str | None, typer.Option(help="Simulate this scene live instead")] = None,
    realtime: Annotated[bool, typer.Option(help="Send at the recorded frame rate")] = True,
    loop: Annotated[bool, typer.Option(help="Start again at the end, forever")] = False,
    fpga_port: Annotated[int | None, typer.Option(
        help="Listen for FPGA packets on this UDP port instead (docs/fpga-link.md)")] = None,
    data_dir: DataDir = DEFAULT_DATA_DIR,
) -> None:
    """Publish frames to the 'frames' topic, from a recording, a live simulation or the FPGA."""
    from upchirp import services, stream
    from upchirp.sources.sim import SimSource

    stream.ensure_topics()
    if fpga_port is not None:
        from upchirp.sources.fpga import FpgaSource

        now = datetime.now(UTC)
        fpga = FpgaSource(f"fpga-{now:%Y%m%dT%H%M%S}Z", port=fpga_port)
        n = services.run_source(fpga.frames(), label="fpga-source")
        r = fpga.reassembler
        typer.echo(f"Published {n} frames; dropped {r.frames_dropped} incomplete, "
                   f"{r.bad_packets} bad packets")
        return
    while True:
        if scene is not None:
            now = datetime.now(UTC)
            sim = Simulator(get_scene(scene), session_id=f"live-{scene}-{now:%Y%m%dT%H%M%S}Z",
                            start_ns=time.time_ns(), seed=int(time.time()))
            frames: Iterator[Frame] = SimSource(sim).frames()
        else:
            frames = ReplaySource(resolve_session(data_dir, session)).frames()
        n = services.run_source(_paced(frames, realtime))
        typer.echo(f"Published {n} frames")
        if not loop:
            return


@app.command("fake-fpga")
def fake_fpga(
    scene: Annotated[str, typer.Option(help="Scene to simulate")] = "default",
    host: Annotated[str, typer.Option(help="Where the FPGA source listens")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="UDP port")] = 4991,
    loop: Annotated[bool, typer.Option(help="Start again at the end, forever")] = False,
) -> None:
    """Pretend to be the FPGA: send a simulated scene as FPGA UDP packets."""
    from upchirp.sources.fpga import send_frames
    from upchirp.sources.sim import SimSource

    while True:
        sc = get_scene(scene)
        sim = Simulator(sc, session_id=f"fake-fpga-{scene}", start_ns=time.time_ns(),
                        seed=int(time.time()))
        n = send_frames(SimSource(sim).frames(), host, port,
                        frame_period_s=sc.frame_period_s)
        typer.echo(f"Sent {n} frames to {host}:{port}")
        if not loop:
            return


@app.command()
def process(from_start: Annotated[bool, typer.Option(help="Read the topic from the start")]
            = False) -> None:
    """Run detection, tracking and labels on every frame in the 'frames' topic."""
    from upchirp import services

    services.run_processor(from_start)


@app.command()
def write(from_start: Annotated[bool, typer.Option(help="Read the topics from the start")]
          = False) -> None:
    """Write detections and tracks from the stream into PostgreSQL."""
    from upchirp import services

    os.environ.setdefault("UPCHIRP_DATABASE_URL", DEV_DATABASE_URL)
    services.run_writer(from_start)


@app.command()
def alerts() -> None:
    """Send a message when a drone-like target appears (Telegram, Slack, or the log)."""
    from upchirp.alerts import run_alerts

    run_alerts()


@app.command()
def api(
    host: Annotated[str, typer.Option(help="Interface to listen on")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port")] = 8000,
    data_dir: DataDir = DEFAULT_DATA_DIR,
) -> None:
    """Serve the REST API, the live WebSocket and the UI."""
    import uvicorn

    from upchirp.api.app import create_app

    os.environ.setdefault("UPCHIRP_DATABASE_URL", DEV_DATABASE_URL)
    uvicorn.run(create_app(data_dir), host=host, port=port, log_level="warning")


@app.command()
def bench(runs: Annotated[int, typer.Option(min=1, help="Answers per scene")] = 5) -> None:
    """Measure the agent's latency, tokens, cost and correctness; write docs/reports/."""
    import tempfile

    from upchirp.agent import bench as agent_bench

    model = agent_bench.model_name()
    with tempfile.TemporaryDirectory() as tmp:
        samples = agent_bench.run(Path(tmp), runs)
    text = agent_bench.report(samples, model)
    safe = "".join(c if c.isalnum() or c in ".-_" else "-" for c in model)
    out = Path(__file__).resolve().parents[2] / "docs" / "reports" / f"agent-bench-{safe}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    typer.echo(text.split("Raw samples")[0])
    typer.echo(f"Written to {out}")


@app.command()
def vectors(
    out: Annotated[Path, typer.Option(help="Output folder")] = Path("dist/fft-vectors"),
    adc_bits: Annotated[int, typer.Option(help="ADC resolution")] = 12,
    window_bits: Annotated[int, typer.Option(help="Window coefficient width")] = 16,
    real_input: Annotated[bool, typer.Option(help="Real ADC samples only (Q is zero)")] = False,
    bit_reversed: Annotated[bool, typer.Option(help="Expected output in bit-reversed order")]
    = False,
    frame: Annotated[int, typer.Option(help="Which frame of the default scene")] = 40,
) -> None:
    """Write range-FFT test vectors for the FPGA (see src/upchirp/dsp/vectors.py)."""
    from upchirp.dsp import vectors as vec

    cfg = vec.VectorConfig(adc_bits=adc_bits, window_bits=window_bits,
                           complex_input=not real_input, bit_reversed_output=bit_reversed)
    sim = Simulator(get_scene("default"), session_id="vectors", start_ns=0, seed=0)
    from itertools import islice

    chosen, _ = next(islice(sim.run(), frame, None))
    data = vec.make_vectors(chosen.cube()[0], cfg)
    vec.write(out, data, cfg, {"scene": "default", "frame": frame, "seed": 0, "rx": 0})
    typer.echo(f"Wrote {data['input_iq'].shape[0]} chirps x {cfg.n_samples} samples to {out}")


@app.command("import-wav")
def import_wav(
    path: Annotated[Path, typer.Argument(help="Stereo WAV: beat signal left, sync right")],
    bandwidth_mhz: Annotated[float, typer.Option(help="VCO sweep bandwidth")] = 80.0,
    sweep_ms: Annotated[float, typer.Option(help="Up-sweep time")] = 20.0,
    notes: Annotated[str, typer.Option(help="Operator notes stored with the session")] = "",
    data_dir: DataDir = DEFAULT_DATA_DIR,
) -> None:
    """Turn a coffee-can sound card recording into a session that replay and the agent can use."""
    from upchirp.config import ArrayConfig
    from upchirp.recording import record_frames
    from upchirp.sources.soundcard import CoffeeCanConfig, SoundcardSource

    cfg = CoffeeCanConfig(bandwidth_hz=bandwidth_mhz * 1e6, sweep_s=sweep_ms / 1e3)
    start_ns = int(path.stat().st_mtime * 1e9)
    session_id = f"can-{path.stem}-{datetime.now(UTC):%Y%m%dT%H%M%S}Z"
    src = SoundcardSource(path, session_id, start_ns, cfg)
    session_dir = record_frames(src.frames(), data_dir, session_id, "soundcard", start_ns,
                                src.chirp, ArrayConfig(n_rx=1), notes,
                                {"recording": path.name, "coffee_can": cfg.__dict__})
    typer.echo(f"Imported {read_manifest(session_dir)['n_frames']} frames as {session_id}")


@app.command("index-docs")
def index_docs() -> None:
    """Embed docs/ into pgvector for the agent's document search."""
    from upchirp import rag, store

    os.environ.setdefault("UPCHIRP_DATABASE_URL", DEV_DATABASE_URL)
    docs = Path(os.environ.get("UPCHIRP_DOCS_DIR", Path(__file__).resolve().parents[2] / "docs"))
    with store.connect() as conn:
        store.init_schema(conn)
        typer.echo(f"Indexed {rag.index_docs(conn, docs)} chunks from {docs}")


@app.command()
def live(
    session: Annotated[str, typer.Option(help="Recording to loop, or 'latest'")] = "latest",
    scene: Annotated[str | None, typer.Option(help="Simulate this scene live instead")] = None,
    port: Annotated[int, typer.Option(help="Port for the UI and API")] = 8000,
    host: Annotated[str, typer.Option(help="Interface for the UI and API")] = "127.0.0.1",
    data_dir: DataDir = DEFAULT_DATA_DIR,
) -> None:
    """Start the whole platform on this machine: processor, writer, API and a looping source.

    Needs the containers from compose.yaml (make up). Stop with Ctrl+C.
    """
    import subprocess
    import sys

    env = {**os.environ, "UPCHIRP_DATABASE_URL": os.environ.get(
        "UPCHIRP_DATABASE_URL", DEV_DATABASE_URL), "UPCHIRP_DATA_DIR": str(data_dir.resolve())}
    base = [sys.executable, "-m", "upchirp.cli"]
    src = ["source", "--loop", "--data-dir", str(data_dir)] + (
        ["--scene", scene] if scene else ["--session", session])
    commands = [["process"], ["write"], ["alerts"],
                ["api", "--host", host, "--port", str(port), "--data-dir", str(data_dir)],
                src]
    procs = []
    try:
        for cmd in commands:
            procs.append(subprocess.Popen(base + cmd, env=env))
            time.sleep(2)
        typer.echo(f"Live view: http://127.0.0.1:{port}  (Ctrl+C to stop)")
        while all(p.poll() is None for p in procs):
            time.sleep(1)
        typer.echo("A service stopped; shutting the rest down.", err=True)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    app()
