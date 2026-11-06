import json


class ResultsService:
    def __init__(self, host):
        self.host = host


    def stop_simulation(self, args):
        run_data = self.host.read_json(self.host.run_path(args["run_id"]))
        process_id = run_data.get("process_id")
        if not process_id:
            return self.host.wrap({"run_id": run_data.get("id"), "stopped": False, "reason": "no_active_process"})
        runtime = self.host.runtime_service
        stop_payload = json.loads(runtime.stop_process({"process_id": process_id})["content"][0]["text"])
        run_data["status"] = "stopped" if stop_payload.get("stopped") else run_data.get("status")
        run_data["end_time"] = self.host.now()
        self.host.write_json(self.host.run_path(run_data["id"]), run_data)
        return self.host.wrap({"run_id": run_data.get("id"), "process_id": process_id, "stopped": bool(stop_payload.get("stopped"))})

    def get_simulation_status(self, args):
        run_data = self.host.read_json(self.host.run_path(args["run_id"]))
        process_id = run_data.get("process_id")
        if process_id and run_data.get("status") in ("created", "running"):
            runtime = self.host.runtime_service
            process_payload = json.loads(runtime.get_process_status({"process_id": process_id})["content"][0]["text"])
            status = process_payload.get("status") or run_data.get("status")
            if status != run_data.get("status"):
                run_data["status"] = status
            if process_payload.get("returncode") is not None:
                run_data.setdefault("outputs", {})["returncode"] = process_payload.get("returncode")
            if process_payload.get("stdout_path"):
                run_data.setdefault("outputs", {})["stdout_path"] = process_payload.get("stdout_path")
            if process_payload.get("stderr_path"):
                run_data.setdefault("outputs", {})["stderr_path"] = process_payload.get("stderr_path")
            run_data["end_time"] = process_payload.get("end_time") or run_data.get("end_time")
            self.host.write_json(self.host.run_path(run_data["id"]), run_data)
        return self.host.wrap(
            {
                "run_id": run_data["id"],
                "status": run_data["status"],
                "start_time": run_data["start_time"],
                "end_time": run_data["end_time"],
                "process_id": process_id,
                "scenario_path": run_data.get("scenario_path"),
                "working_dir": run_data.get("working_dir"),
            }
        )









