import re

def parse_maestro_yaml(yaml_content):
    """
    Parses a Maestro YAML file line-by-line.
    Extracts the appId header and list of steps (action and optional parameter value).
    """
    lines = yaml_content.split('\n')
    app_id = "com.konn3ct.mobile"
    steps = []
    
    # 1. Extract appId
    for line in lines:
        if line.strip().startswith("appId:"):
            app_id = line.split("appId:")[1].strip()
            break
            
    # 2. Extract steps following the --- separator
    in_steps = False
    for line in lines:
        line_stripped = line.strip()
        if line_stripped == "---":
            in_steps = True
            continue
        if not in_steps:
            continue
            
        if line_stripped.startswith("-"):
            step_content = line_stripped[1:].strip()
            if not step_content:
                continue
                
            # If step is a key-value pair (e.g. tapOn: "Room Code")
            if ":" in step_content:
                parts = step_content.split(":", 1)
                action = parts[0].strip()
                val = parts[1].strip()
                # Strip wrapping quotes
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                steps.append({
                    "action": action,
                    "value": val
                })
            else:
                steps.append({
                    "action": step_content,
                    "value": ""
                })
                
    return {
        "appId": app_id,
        "steps": steps
    }

def serialize_maestro_yaml(app_id, steps):
    """
    Converts a JSON list of steps back into a standard Maestro YAML string.
    """
    yaml_lines = []
    yaml_lines.append(f"appId: {app_id}")
    yaml_lines.append("---")
    
    for s in steps:
        action = s.get("action", "").strip()
        value = s.get("value", "")
        
        if not action:
            continue
            
        if value:
            # Escape internal double quotes and wrap value
            escaped_val = str(value).replace('"', '\\"')
            yaml_lines.append(f"- {action}: \"{escaped_val}\"")
        else:
            yaml_lines.append(f"- {action}")
            
    return "\n".join(yaml_lines) + "\n"
