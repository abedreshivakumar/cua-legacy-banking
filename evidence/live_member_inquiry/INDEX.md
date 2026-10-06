# Evidence: member_inquiry — REAL live claude-opus-5-5 discovery run

## Discovery run
- run_id: `2aab947b-cd4e-40c3-b764-709a419da457`
- status: `completed`
- actions logged: 9
- transcript: [2aab947b-cd4e-40c3-b764-709a419da457.transcript.txt](./2aab947b-cd4e-40c3-b764-709a419da457.transcript.txt)

## Compiled artifact
- [member_inquiry_live-0.0.1.yaml](./member_inquiry_live-0.0.1.yaml)

## Replay runs (deterministic, zero model calls)
- **happy path (replay of the compiled artifact)**: status=`succeeded`, run_id=`15316827-a715-4e53-9854-762d147fe6e0`, side_effects_committed=`none` — [happy_path.15316827-a715-4e53-9854-762d147fe6e0.replay.json](./happy_path.15316827-a715-4e53-9854-762d147fe6e0.replay.json)
- **error path (member 999999 does not exist)**: status=`failed`, code=`postcondition_timeout`, run_id=`d56340f2-4995-4a6c-a8b5-05e141541e1c`, side_effects_committed=`none` — [error_path.d56340f2-4995-4a6c-a8b5-05e141541e1c.replay.json](./error_path.d56340f2-4995-4a6c-a8b5-05e141541e1c.replay.json)

## Screenshots
- **error path — results page**: [error_path_screenshot.png](./error_path_screenshot.png)
