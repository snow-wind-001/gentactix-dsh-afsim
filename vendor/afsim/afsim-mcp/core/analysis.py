import re
from collections import defaultdict
from pathlib import Path

# Platform and sensor names use underscores, dashes and dots as separators
# (BLUE_FIGHTER_1, F-22, SAM-3), so a plain substring test produces false
# positives: "us" matches RUSSIAN_FIGHTER, "sam" matches SAMPLE.
_TOKEN_SPLIT_RE = re.compile(r"[^a-z0-9]+")

# AFSIM writes the event time in whichever format the run's event_output
# selected; all three occur in the demos shipped with the product -- plain
# seconds ("6758.17395"), hours:minutes:seconds ("00:12:26.8") and a zero-
# padded variant. Anchoring on the decimal form alone silently returned zero
# records for a whole run.
_EVT_RECORD_RE = re.compile(r"^(\d+(?::\d+){1,2}(?:\.\d+)?|\d+(?:\.\d+)?)\s+([A-Z_]+)\s*(.*)$")


def _evt_time_seconds(stamp):
    if ":" in stamp:
        hours, minutes, seconds = stamp.split(":")
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return float(stamp)


def name_tokens(value):
    return {token for token in _TOKEN_SPLIT_RE.split(str(value or "").lower()) if token}


class AnalysisService:
    _BLUE_SIDE_TOKENS = {"blue", "israel", "israeli", "us", "usa", "friendly", "west", "nato"}
    _RED_SIDE_TOKENS = {"red", "iran", "iranian", "russia", "russian", "hostile", "east"}

    def __init__(self, host):
        self.host = host


    def analyze_scenario_outputs(self, args):
        scenario_dir_arg = args.get("scenario_dir")
        evt_arg = args.get("evt_path")
        sensor_arg = args.get("sensor_path")
        aer_arg = args.get("aer_path")

        if not scenario_dir_arg and not evt_arg:
            raise self.host.JsonRpcError(
                -32602,
                "Invalid params",
                {"reason": "scenario_dir or evt_path is required"},
            )

        scenario_dir = Path(scenario_dir_arg) if scenario_dir_arg else None
        if scenario_dir:
            self.host.assert_path_allowed(scenario_dir, write=True, purpose="analyze_scenario_outputs(scenario_dir)")

        evt_path = Path(evt_arg) if evt_arg else self.host.find_latest_matching_file(scenario_dir, "*.evt")
        if not evt_path or not evt_path.exists():
            return self.host.wrap({"error": "evt file not found"})
        self.host.assert_path_allowed(evt_path, write=False, purpose="analyze_scenario_outputs(evt)")

        sensor_path = Path(sensor_arg) if sensor_arg else self.host.find_latest_matching_file(scenario_dir, "SENSOR*")
        if sensor_path and sensor_path.exists():
            self.host.assert_path_allowed(sensor_path, write=False, purpose="analyze_scenario_outputs(sensor)")
        else:
            sensor_path = None

        aer_path = Path(aer_arg) if aer_arg else self.host.find_latest_matching_file(scenario_dir, "*.aer")
        if aer_path and aer_path.exists():
            self.host.assert_path_allowed(aer_path, write=False, purpose="analyze_scenario_outputs(aer)")
        else:
            aer_path = None

        records = self.parse_evt_records(evt_path)
        analysis = self.build_output_analysis(
            records,
            scenario_dir=scenario_dir,
            evt_path=evt_path,
            sensor_path=sensor_path,
            aer_path=aer_path,
        )

        output_path = args.get("output_path")
        if output_path:
            output_json_path = Path(output_path)
        elif scenario_dir:
            output_json_path = scenario_dir / "doc" / "ANALYSIS.json"
        else:
            output_json_path = None

        output_md_path = None
        if output_json_path:
            self.host.assert_path_allowed(output_json_path, write=True, purpose="analyze_scenario_outputs(output_json)")
            self.host.write_json(output_json_path, analysis)
            output_md_path = output_json_path.with_suffix(".md")
            self.host.assert_path_allowed(output_md_path, write=True, purpose="analyze_scenario_outputs(output_md)")
            self.host.write_text(output_md_path, self.render_analysis_markdown(analysis))

        return self.host.wrap(
            {
                "analysis": analysis,
                "analysis_path": str(output_json_path) if output_json_path else None,
                "analysis_markdown_path": str(output_md_path) if output_md_path else None,
            }
        )

    def parse_evt_records(self, evt_path):
        raw_lines = Path(evt_path).read_text(encoding="utf-8", errors="ignore").splitlines()
        combined = []
        buffer = ""
        for line in raw_lines:
            stripped = line.strip()
            if not stripped:
                continue
            if buffer:
                buffer = f"{buffer} {stripped}"
            else:
                buffer = stripped
            if stripped.endswith("\\"):
                buffer = buffer[:-1].rstrip()
                continue
            combined.append(buffer)
            buffer = ""
        if buffer:
            combined.append(buffer)

        records = []
        for record in combined:
            match = _EVT_RECORD_RE.match(record)
            if not match:
                continue
            time_sec = _evt_time_seconds(match.group(1))
            event_type = match.group(2)
            payload = match.group(3).strip()
            prefix, fields = self.parse_evt_payload_fields(payload)
            tokens = prefix.split() if prefix else []
            records.append(
                {
                    "time_sec": time_sec,
                    "event_type": event_type,
                    "prefix": prefix,
                    "tokens": tokens,
                    "fields": fields,
                    "raw": record,
                }
            )
        return records

    def parse_evt_payload_fields(self, payload):
        first_field = re.search(r"\b[A-Za-z_][A-Za-z0-9_]*:\s", payload)
        if not first_field:
            return payload.strip(), {}
        prefix = payload[: first_field.start()].strip()
        field_text = payload[first_field.start() :]
        fields = {}
        for key, value in re.findall(r"([A-Za-z_][A-Za-z0-9_]*):\s*(.*?)(?=\s+[A-Za-z_][A-Za-z0-9_]*:\s|$)", field_text):
            fields[key] = value.strip()
        return prefix, fields

    def build_diagnostics(self, records, event_counts, *, evt_path, scenario_dir):
        """Say why a report is thin, instead of returning all-null KPIs silently.

        An empty .evt usually means the scenario's event_output block enables no
        events -- the AFSIM demos ship with several entries where every enable
        line is commented out -- which is very different from a run that placed
        platforms and never engaged.
        """
        notes = []
        total = sum(event_counts.values())

        if evt_path and Path(evt_path).is_file() and Path(evt_path).stat().st_size == 0:
            notes.append(
                {
                    "issue": "empty_evt",
                    "detail": f"{evt_path} is 0 bytes.",
                    "likely_cause": "The scenario's event_output block enables no events, or "
                    "its file path is never written. Check for commented-out 'enable' lines.",
                }
            )

        if total == 0:
            notes.append(
                {
                    "issue": "no_events",
                    "detail": "The .evt file contains no records.",
                    "likely_cause": "Nothing in the scenario emitted events. Enable at least "
                    "PLATFORM_INITIALIZED, SENSOR_TRACK_UPDATED and WEAPON_FIRED in "
                    "event_output before drawing conclusions.",
                }
            )
        elif set(event_counts) <= {"PLATFORM_INITIALIZED"}:
            notes.append(
                {
                    "issue": "placement_only",
                    "detail": "Only PLATFORM_INITIALIZED events were recorded.",
                    "likely_cause": "The platforms were placed but nothing detected, tracked or "
                    "fired. Either the platforms carry no sensor/weapon components, or "
                    "event_output does not enable those event types.",
                }
            )

        missing = [k for k in ("PLATFORM_BROKEN", "WEAPON_FIRED", "WEAPON_HIT") if k not in event_counts]
        if missing and total:
            notes.append(
                {
                    "issue": "event_types_absent",
                    "detail": f"No {', '.join(missing)} events in the .evt file.",
                    "likely_cause": "Either nothing happened, or these event types are not "
                    "enabled in the scenario's event_output block.",
                }
            )

        # Sustained tracking with no shot in the entire run is its own failure
        # shape, distinct from silence: the sensors work, the engagement
        # decision never follows. This is the signature of a tactics processor
        # that is wired on the type but not on the instance.
        track_events = sum(
            count for name, count in event_counts.items() if name.startswith("SENSOR_TRACK")
        )
        if (
            track_events >= 10
            and not event_counts.get("WEAPON_FIRED")
            and not event_counts.get("PLATFORM_BROKEN")
        ):
            notes.append(
                {
                    "issue": "tracking_without_engagement",
                    "detail": f"{track_events} sensor track events, but no WEAPON_FIRED "
                    "or PLATFORM_BROKEN in the entire run.",
                    "likely_cause": "The sides detected each other but no engagement "
                    "decision followed. The common cause is a tactics processor that is "
                    "wired on the type but not on the instance: families such as "
                    "BRAWLER_TEST need commander / command_chain on each platform plus "
                    "the script_variables their scripts read (MISSION_TYPE, ROUTE, "
                    "WINCHESTER, ...). afsim_types(name=<type>) returns "
                    "demo_instantiations showing how the demos wire the type.",
                }
            )

        if not scenario_dir:
            notes.append(
                {
                    "issue": "no_scenario_dir",
                    "detail": "No scenario_dir was supplied.",
                    "likely_cause": "Only the .evt was read, so SENSOR/AER companion outputs "
                    "could not be correlated.",
                }
            )
        return notes

    def build_output_analysis(self, records, *, scenario_dir=None, evt_path=None, sensor_path=None, aer_path=None):
        event_counts = defaultdict(int)
        timeline = []
        losses = {
            "blue": {"platforms_lost": 0, "aircraft": 0, "ground": 0, "targets": 0, "weapons_expended": 0},
            "red": {"platforms_lost": 0, "aircraft": 0, "ground": 0, "targets": 0, "weapons_expended": 0},
            "unknown": {"platforms_lost": 0, "aircraft": 0, "ground": 0, "targets": 0, "weapons_expended": 0},
        }
        weapon_stats = defaultdict(lambda: {"resolved_engagements": 0, "hits": 0, "misses": 0, "top_shooters": defaultdict(int)})
        intercept_stats = defaultdict(lambda: {"attempted_intercepts": 0, "successful_intercepts": 0})
        sensor_chains = {}
        first_detection_by_side = {}
        first_shot_by_side = {}
        first_hit_by_side = {}
        first_kill_by_side = {}
        broken_platforms = set()
        objective_inventory_by_side = defaultdict(set)
        # Provenance evidence, read out of the event stream itself rather than
        # guessed from names.  AFSIM names a launched weapon platform
        # "<shooter>:<weapon instance>" and reports that exact string as the
        # third token of WEAPON_FIRED, so a PLATFORM_BROKEN whose name was
        # announced by a launch is an expended round, not a combat loss.
        # PLATFORM_INITIALIZED is the other half: whatever the scenario placed
        # on the field was a real platform from the start.
        launched_weapon_platforms = set()
        initialized_platforms = set()
        unverified_losses = []

        for record in records:
            event_type = record["event_type"]
            event_counts[event_type] += 1
            timeline_item = self.event_to_timeline_item(record)
            if timeline_item:
                timeline.append(timeline_item)

            if event_type == "WEAPON_FIRED":
                shooter = record["tokens"][0] if len(record["tokens"]) > 0 else None
                side = self.infer_side(shooter)
                self.update_first_event_time(first_shot_by_side, side, record["time_sec"])
                if len(record["tokens"]) > 2:
                    launched_weapon_platforms.add(record["tokens"][2])

            if event_type in ("WEAPON_HIT", "WEAPON_MISSED"):
                shooter = record["tokens"][0] if len(record["tokens"]) > 0 else None
                target = record["tokens"][1] if len(record["tokens"]) > 1 else None
                side = self.infer_side(shooter)
                stats = weapon_stats[side]
                stats["resolved_engagements"] += 1
                stats["hits" if event_type == "WEAPON_HIT" else "misses"] += 1
                self.update_first_event_time(first_shot_by_side, side, record["time_sec"])
                if shooter:
                    stats["top_shooters"][shooter] += 1
                if target in launched_weapon_platforms:
                    intercept = intercept_stats[side]
                    intercept["attempted_intercepts"] += 1
                    if event_type == "WEAPON_HIT":
                        intercept["successful_intercepts"] += 1
                if event_type == "WEAPON_HIT":
                    self.update_first_event_time(first_hit_by_side, side, record["time_sec"])

            if event_type == "PLATFORM_BROKEN":
                platform = record["tokens"][0] if record["tokens"] else "unknown"
                side = str(record["fields"].get("Side") or self.infer_side(platform))
                bucket, basis = self.classify_loss_bucket(
                    record["fields"].get("Type"),
                    platform,
                    launched=launched_weapon_platforms,
                    initialized=initialized_platforms,
                )
                broken_platforms.add(platform)
                losses.setdefault(side, {"platforms_lost": 0, "aircraft": 0, "ground": 0, "targets": 0, "weapons_expended": 0})
                if bucket == "weapons_expended":
                    losses[side][bucket] += 1
                else:
                    losses[side]["platforms_lost"] += 1
                    losses[side][bucket] += 1
                    if basis == "unverified":
                        unverified_losses.append({"platform": platform, "side": side, "type": record["fields"].get("Type")})
                    self.update_first_event_time(first_kill_by_side, self.opposing_side(side), record["time_sec"])

            if event_type == "PLATFORM_INITIALIZED":
                platform = record["tokens"][0] if record["tokens"] else "unknown"
                initialized_platforms.add(platform)
                side = str(record["fields"].get("Side") or self.infer_side(platform))
                platform_type = record["fields"].get("Type")
                if self.is_objective_platform(platform_type, platform):
                    objective_inventory_by_side[side].add(platform)

            if event_type in ("SENSOR_TRACK_INITIATED", "SENSOR_TRACK_UPDATED"):
                observer = record["tokens"][0] if len(record["tokens"]) > 0 else "unknown"
                target = record["tokens"][1] if len(record["tokens"]) > 1 else "unknown"
                sensor = record["fields"].get("Sensor") or "unknown"
                track_id = record["fields"].get("TrackId") or f"{observer}:{target}:{sensor}"
                self.update_first_event_time(first_detection_by_side, self.infer_side(observer), record["time_sec"])
                chain = sensor_chains.setdefault(
                    track_id,
                    {
                        "track_id": track_id,
                        "observer": observer,
                        "target": target,
                        "sensor": sensor,
                        "side": self.infer_side(observer),
                        "first_detected_sec": record["time_sec"],
                        "last_update_sec": record["time_sec"],
                        "update_count": 0,
                    },
                )
                chain["last_update_sec"] = record["time_sec"]
                if event_type == "SENSOR_TRACK_UPDATED":
                    chain["update_count"] += 1

        weapon_summary = {}
        for side, stats in weapon_stats.items():
            resolved = stats["resolved_engagements"]
            weapon_summary[side] = {
                "resolved_engagements": resolved,
                "hits": stats["hits"],
                "misses": stats["misses"],
                "hit_rate": round(stats["hits"] / resolved, 3) if resolved else 0.0,
                "top_shooters": [
                    {"shooter": shooter, "engagements": count}
                    for shooter, count in sorted(stats["top_shooters"].items(), key=lambda item: item[1], reverse=True)[:5]
                ],
            }

        intercept_summary = {}
        for side, stats in intercept_stats.items():
            attempted = stats["attempted_intercepts"]
            intercept_summary[side] = {
                "attempted_intercepts": attempted,
                "successful_intercepts": stats["successful_intercepts"],
                "interception_rate": round(stats["successful_intercepts"] / attempted, 3) if attempted else 0.0,
            }

        chains = sorted(sensor_chains.values(), key=lambda item: item["first_detected_sec"])
        keyframes = self.build_recommended_keyframes(timeline, chains, aer_path)
        kpi_summary = self.build_kpi_summary(
            first_detection_by_side,
            first_shot_by_side,
            first_hit_by_side,
            first_kill_by_side,
            broken_platforms,
            objective_inventory_by_side,
            losses,
            chains,
            timeline,
        )

        highlights = []
        if chains:
            first_chain = chains[0]
            highlights.append(
                f"First sensor chain started at {self.host.format_time_label(first_chain['first_detected_sec'])} by {first_chain['observer']} tracking {first_chain['target']}."
            )
        for side in ("blue", "red"):
            if side in weapon_summary and weapon_summary[side]["resolved_engagements"]:
                highlights.append(
                    f"{side.title()} resolved {weapon_summary[side]['resolved_engagements']} engagements with a hit rate of {weapon_summary[side]['hit_rate']}."
                )
        for side in ("blue", "red"):
            if losses.get(side, {}).get("platforms_lost"):
                highlights.append(
                    f"{side.title()} lost {losses[side]['platforms_lost']} non-weapon platforms."
                )
        if kpi_summary.get("kill_chain_closure"):
            highlights.append(
                f"Kill-chain closure score: {kpi_summary['kill_chain_closure']['score']} / 100."
            )

        return {
            "scenario_dir": str(scenario_dir) if scenario_dir else None,
            "evt_path": str(evt_path) if evt_path else None,
            "sensor_path": str(sensor_path) if sensor_path else None,
            "aer_path": str(aer_path) if aer_path else None,
            "event_counts": dict(sorted(event_counts.items(), key=lambda item: item[1], reverse=True)),
            "timeline": timeline[:40],
            "timeline_truncated_at": 40 if len(timeline) > 40 else None,
            # The timeline is a curated subset, so the real span of the run has
            # to come from every parsed record, not from it.
            "first_event_sec": min((r["time_sec"] for r in records), default=None),
            "last_event_sec": max((r["time_sec"] for r in records), default=None),
            "records_parsed": len(records),
            "red_blue_losses": losses,
            "loss_accounting": self.build_loss_accounting(
                launched_weapon_platforms, initialized_platforms, unverified_losses
            ),
            "weapon_statistics": weapon_summary,
            "interception_statistics": intercept_summary,
            "sensor_detection_chains": chains[:20],
            "kpis": kpi_summary,
            "recommended_keyframes": keyframes,
            "highlights": highlights,
            "diagnostics": self.build_diagnostics(
                records, event_counts, evt_path=evt_path, scenario_dir=scenario_dir
            ),
        }

    def event_to_timeline_item(self, record):
        event_type = record["event_type"]
        time_sec = record["time_sec"]
        if event_type == "WEAPON_FIRED":
            shooter = record["tokens"][0] if len(record["tokens"]) > 0 else "unknown"
            target = record["tokens"][1] if len(record["tokens"]) > 1 else "unknown"
            weapon = record["tokens"][2] if len(record["tokens"]) > 2 else "unknown_weapon"
            return {
                "time_sec": time_sec,
                "time_label": self.host.format_time_label(time_sec),
                "event_type": event_type,
                "title": f"{weapon} fired at {target}",
                "detail": f"{shooter} launched {weapon} against {target}.",
            }
        if event_type in ("WEAPON_HIT", "WEAPON_MISSED"):
            shooter = record["tokens"][0] if len(record["tokens"]) > 0 else "unknown"
            target = record["tokens"][1] if len(record["tokens"]) > 1 else "unknown"
            weapon = record["tokens"][2] if len(record["tokens"]) > 2 else "unknown_weapon"
            outcome = "hit" if event_type == "WEAPON_HIT" else "missed"
            return {
                "time_sec": time_sec,
                "time_label": self.host.format_time_label(time_sec),
                "event_type": event_type,
                "title": f"{weapon} {outcome} {target}",
                "detail": f"{shooter} engaged {target} using {weapon}.",
            }
        if event_type == "PLATFORM_BROKEN":
            platform = record["tokens"][0] if record["tokens"] else "unknown"
            return {
                "time_sec": time_sec,
                "time_label": self.host.format_time_label(time_sec),
                "event_type": event_type,
                "title": f"{platform} broken",
                "detail": f"{platform} left the fight.",
            }
        if event_type == "SENSOR_TRACK_INITIATED":
            observer = record["tokens"][0] if len(record["tokens"]) > 0 else "unknown"
            target = record["tokens"][1] if len(record["tokens"]) > 1 else "unknown"
            sensor = record["fields"].get("Sensor") or "sensor"
            return {
                "time_sec": time_sec,
                "time_label": self.host.format_time_label(time_sec),
                "event_type": event_type,
                "title": f"Track initiated on {target}",
                "detail": f"{observer} detected {target} with {sensor}.",
            }
        return None

    def build_recommended_keyframes(self, timeline, chains, aer_path):
        keyframes = []
        seen_titles = set()
        if chains:
            first_chain = chains[0]
            keyframes.append(
                {
                    "time_sec": first_chain["first_detected_sec"],
                    "time_label": self.host.format_time_label(first_chain["first_detected_sec"]),
                    "title": f"First detection: {first_chain['target']}",
                    "focus": f"Observer {first_chain['observer']} and target {first_chain['target']}",
                    "recommended_view": "Start wide, then anchor on the detecting unit and its target.",
                    "aer_path": str(aer_path) if aer_path else None,
                }
            )
            seen_titles.add(keyframes[-1]["title"])
        for item in timeline:
            if len(keyframes) >= 8:
                break
            if item["title"] in seen_titles:
                continue
            keyframes.append(
                {
                    "time_sec": item["time_sec"],
                    "time_label": item["time_label"],
                    "title": item["title"],
                    "focus": item["detail"],
                    "recommended_view": "Center the camera on the engaged pair and hold for 10-15 seconds.",
                    "aer_path": str(aer_path) if aer_path else None,
                }
            )
            seen_titles.add(item["title"])
        return keyframes

    def build_kpi_summary(self, first_detection_by_side, first_shot_by_side, first_hit_by_side, first_kill_by_side, broken_platforms, objective_inventory_by_side, losses, chains, timeline):
        side_kpis = {}
        for side in ("blue", "red"):
            side_kpis[side] = {
                "first_detection_sec": first_detection_by_side.get(side),
                "first_detection_label": self.format_optional_time(first_detection_by_side.get(side)),
                "first_shot_sec": first_shot_by_side.get(side),
                "first_shot_label": self.format_optional_time(first_shot_by_side.get(side)),
                "first_hit_sec": first_hit_by_side.get(side),
                "first_hit_label": self.format_optional_time(first_hit_by_side.get(side)),
                "first_kill_sec": first_kill_by_side.get(side),
                "first_kill_label": self.format_optional_time(first_kill_by_side.get(side)),
                "platforms_lost": losses.get(side, {}).get("platforms_lost", 0),
            }

        # Objectives are identified from PLATFORM_INITIALIZED events alone: the
        # *.model.json that used to describe them came from a generation
        # pipeline that no longer exists.
        objective_survival = self.compute_event_objective_survival(
            objective_inventory_by_side, broken_platforms
        )
        if not objective_survival:
            objective_survival = {
                "status": "not_applicable",
                "reason": "No platform was identified as an objective. This is expected for "
                "a scenario with no targets; enable PLATFORM_INITIALIZED in event_output and "
                "give the target platform a name or type that reads as one (target, airbase, "
                "hvaa, ...).",
            }
        kill_chain = self.compute_kill_chain_closure(first_detection_by_side, first_shot_by_side, first_hit_by_side, first_kill_by_side, chains, timeline)

        return {
            "side_kpis": side_kpis,
            "objective_survival": objective_survival,
            "kill_chain_closure": kill_chain,
            "kill_attribution": (
                "first_kill is inferred from PLATFORM_BROKEN by assigning the loss to the "
                "opposing side, because AFSIM's event output does not record the shooter on "
                "a destruction. A platform lost to fuel exhaustion, a crash or mutual "
                "destruction will be attributed to the enemy. Cross-check against "
                "weapon_statistics before drawing conclusions."
            ),
        }

    def build_loss_accounting(self, launched, initialized, unverified):
        """Report where the loss numbers came from, so a reader can weigh them.

        red_blue_losses is only as trustworthy as the evidence behind it.  A
        run whose event_output omits WEAPON_FIRED and PLATFORM_INITIALIZED
        cannot separate an expended round from a destroyed aircraft, and saying
        so is more useful than a number that looks precise and is not.
        """
        return {
            "basis": "AFSIM event stream (WEAPON_FIRED / PLATFORM_INITIALIZED), not name spelling",
            "launched_weapon_platforms": len(launched),
            "initialized_platforms": len(initialized),
            "unverified_losses": unverified,
            "unverified_loss_count": len(unverified),
            "note": (
                "A PLATFORM_BROKEN whose name was announced by a WEAPON_FIRED is an "
                "expended round and is not counted as a combat loss. A loss is "
                "'unverified' when neither a launch record nor a PLATFORM_INITIALIZED "
                "record covers it -- usually because the .evt is truncated or "
                "event_output omits those event types."
            )
            if unverified
            else "Every combat loss in this run is backed by a PLATFORM_INITIALIZED record.",
        }

    def compute_event_objective_survival(self, objective_inventory_by_side, broken_platforms):
        summary = {}
        for side, platforms in objective_inventory_by_side.items():
            total = len(platforms)
            if total == 0:
                continue
            broken = sum(1 for name in platforms if name in broken_platforms)
            summary[side] = {
                "total_objectives": total,
                "surviving_objectives": max(total - broken, 0),
                "survival_rate": round(max(total - broken, 0) / total, 3) if total else 0.0,
            }
        return summary

    def compute_kill_chain_closure(self, first_detection_by_side, first_shot_by_side, first_hit_by_side, first_kill_by_side, chains, timeline):
        first_detection = min(first_detection_by_side.values()) if first_detection_by_side else None
        first_shot = min(first_shot_by_side.values()) if first_shot_by_side else None
        first_hit = min(first_hit_by_side.values()) if first_hit_by_side else None
        first_kill = min(first_kill_by_side.values()) if first_kill_by_side else None

        components = {
            "detection_observed": first_detection is not None,
            "weapon_employed": first_shot is not None and (first_detection is None or first_shot >= first_detection),
            "weapon_effect_observed": first_hit is not None and (first_shot is None or first_hit >= first_shot),
            "kill_or_break_observed": first_kill is not None and (first_hit is None or first_kill >= first_hit),
            "sensor_to_shooter_link": bool(chains) and any(item["event_type"] in ("WEAPON_FIRED", "WEAPON_HIT", "WEAPON_MISSED") for item in timeline),
        }
        score = sum(20 for value in components.values() if value)
        return {
            "score": score,
            "components": components,
            "first_detection_label": self.format_optional_time(first_detection),
            "first_shot_label": self.format_optional_time(first_shot),
            "first_hit_label": self.format_optional_time(first_hit),
            "first_kill_label": self.format_optional_time(first_kill),
        }

    def update_first_event_time(self, store, side, value):
        if side not in store or value < store[side]:
            store[side] = value

    def opposing_side(self, side):
        if side == "blue":
            return "red"
        if side == "red":
            return "blue"
        return "unknown"

    def format_optional_time(self, seconds):
        if seconds is None:
            return None
        return self.host.format_time_label(seconds)

    def infer_side(self, name):
        tokens = name_tokens(name)
        if tokens & self._BLUE_SIDE_TOKENS:
            return "blue"
        if tokens & self._RED_SIDE_TOKENS:
            return "red"
        return "unknown"

    def classify_loss_bucket(self, platform_type, platform_name, *, launched=frozenset(), initialized=frozenset()):
        """Bucket a PLATFORM_BROKEN record and say which evidence decided it.

        The bucket is never inferred from the spelling of a name.  AFSIM's own
        event stream carries the provenance: a round that was launched appears
        as the third token of its WEAPON_FIRED record, and a platform the
        scenario placed appears in PLATFORM_INITIALIZED.  When neither record
        is available -- a truncated .evt, or event_output that omits those
        types -- the loss is reported as a real loss of unknown role and the
        caller is told the basis was unverified.  A substring fallback used to
        cover that gap and misread every SAM site as a missile, because "sam"
        is inside "BLUE_SAM_SITE"; a number that is wrong in the direction of
        looking good is worse than one that admits it is unsupported.
        """
        if platform_name in launched:
            return "weapons_expended", "evt_launch_record"
        if initialized and platform_name in initialized:
            return self.domain_bucket(platform_type, platform_name), "evt_initialization_record"
        return self.domain_bucket(platform_type, platform_name), "unverified"

    def domain_bucket(self, platform_type, platform_name):
        """Split a verified combat loss into aircraft / objective / ground.

        The domain comes from the AFSIM type index, which reads the platform's
        declared mover out of the AFSIM libraries.  A substring test on the
        name was tried first and filed seven lost bombers under "ground"
        because the word "bomber" contains neither "air" nor "fighter".
        """
        domain = self.declared_domain(platform_type)
        if domain == "air":
            return "aircraft"
        if self.is_objective_platform(platform_type, platform_name):
            return "targets"
        return "ground"

    def declared_domain(self, platform_type):
        index = getattr(self.host, "type_index", None)
        if index is None or not platform_type:
            return None
        try:
            entry = index.catalog_entry(platform_type)
        except Exception:
            return None
        if not entry:
            return None
        domain = entry.get("domain")
        return None if domain == "undetermined" else domain

    def is_objective_platform(self, platform_type, platform_name):
        text = f"{platform_type or ''} {platform_name or ''}".lower()
        return any(token in text for token in ["target", "airbase", "base", "hvaa", "command", "c2", "hq", "depot"])

    def render_analysis_markdown(self, analysis):
        lines = [
            "# Output Analysis",
            "",
            "## Highlights",
            "",
        ]
        for highlight in analysis.get("highlights", []):
            lines.append(f"- {highlight}")
        kpis = analysis.get("kpis") or {}
        if kpis:
            lines.extend(["", "## KPI Summary", ""])
            kill_chain = kpis.get("kill_chain_closure") or {}
            if kill_chain:
                lines.append(f"- kill_chain_closure_score: {kill_chain.get('score')}")
                for name, value in (kill_chain.get("components") or {}).items():
                    lines.append(f"- {name}: {value}")
            for side, stats in (kpis.get("side_kpis") or {}).items():
                lines.append(f"### {side.title()} Tempo")
                lines.append("")
                lines.append(f"- first_detection: {stats.get('first_detection_label') or 'n/a'}")
                lines.append(f"- first_shot: {stats.get('first_shot_label') or 'n/a'}")
                lines.append(f"- first_hit: {stats.get('first_hit_label') or 'n/a'}")
                lines.append(f"- first_kill: {stats.get('first_kill_label') or 'n/a'}")
                lines.append(f"- platforms_lost: {stats.get('platforms_lost', 0)}")
                lines.append("")
            objective_survival = kpis.get("objective_survival") or {}
            if objective_survival:
                lines.append("## Objective Survival")
                lines.append("")
                if "status" in objective_survival:
                    lines.append(f"- status: {objective_survival['status']}")
                    lines.append(f"- reason: {objective_survival.get('reason')}")
                    lines.append("")
                else:
                    for side, stats in objective_survival.items():
                        if not isinstance(stats, dict):
                            continue
                        lines.append(f"### {side.title()}")
                        lines.append("")
                        lines.append(f"- total_objectives: {stats.get('total_objectives', 0)}")
                        lines.append(f"- surviving_objectives: {stats.get('surviving_objectives', 0)}")
                        lines.append(f"- survival_rate: {stats.get('survival_rate', 0.0)}")
                        lines.append("")
        diagnostics = analysis.get("diagnostics") or []
        if diagnostics:
            lines.extend(["", "## Diagnostics", ""])
            for note in diagnostics:
                lines.append(f"- **{note['issue']}**: {note['detail']}")
                lines.append(f"  - {note['likely_cause']}")
            lines.append("")
        lines.extend(["", "## Red-Blue Losses", ""])
        for side, stats in analysis.get("red_blue_losses", {}).items():
            lines.append(f"### {side.title()}")
            lines.append("")
            for key, value in stats.items():
                lines.append(f"- {key}: {value}")
            lines.append("")
        lines.extend(["## Weapon Statistics", ""])
        for side, stats in analysis.get("weapon_statistics", {}).items():
            lines.append(f"### {side.title()}")
            lines.append("")
            lines.append(f"- resolved_engagements: {stats['resolved_engagements']}")
            lines.append(f"- hits: {stats['hits']}")
            lines.append(f"- misses: {stats['misses']}")
            lines.append(f"- hit_rate: {stats['hit_rate']}")
            for shooter in stats.get("top_shooters", []):
                lines.append(f"- top_shooter {shooter['shooter']}: {shooter['engagements']}")
            lines.append("")
        lines.extend(["## Recommended Keyframes", ""])
        for keyframe in analysis.get("recommended_keyframes", []):
            lines.append(f"- {keyframe['time_label']} {keyframe['title']}: {keyframe['focus']}")
        return "\n".join(lines).rstrip() + "\n"