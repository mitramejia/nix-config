{lib}: let
  # Each agent is one file: OpenCode Markdown agents plus the prompts shared with Codex.
  agentFiles = dir: suffix:
    lib.mapAttrs' (file: _: lib.nameValuePair (lib.removeSuffix suffix file) (dir + "/${file}"))
    (lib.filterAttrs (file: type: type == "regular" && lib.hasSuffix suffix file) (builtins.readDir dir));
  # Stop at the first closing delimiter, not a later Markdown horizontal rule.
  fromMarkdown = path: let
    lines = lib.splitString "\n" (lib.replaceStrings ["\r\n"] ["\n"] (builtins.readFile path));
    rest = builtins.tail lines;
    end = lib.lists.findFirstIndex (line: builtins.elem line ["---" "..."]) null rest;
    header = lib.take end rest;
    descriptions = builtins.filter (lib.hasPrefix "description: ") header;
    # A V2 rule's fields follow its "  - action:" line until the next rule.
    ruleFields = start: let
      following = lib.drop (start + 1) header;
    in
      lib.take (lib.lists.findFirstIndex (lib.hasPrefix "  - ") (builtins.length following) following) following;
  in
    assert builtins.head lines == "---" && end != null;
    assert builtins.length descriptions == 1; {
      original = builtins.readFile path;
      format = "markdown";
      description = lib.removePrefix "description: " (builtins.head descriptions);
      body = lib.concatStringsSep "\n" (lib.drop (end + 1) rest);
      readOnly = lib.any (i: builtins.elemAt header i == "  - action: edit" && builtins.elem "    effect: deny" (ruleFields i)) (lib.range 0 (end - 1));
    };
  # Agents shared with Codex commit or review; Claude never lets them edit files.
  fromToml = path: let
    agent = builtins.fromTOML (builtins.readFile path);
  in {
    original = builtins.readFile path;
    format = "toml";
    inherit (agent) description;
    body = agent.developer_instructions;
    readOnly = true;
  };
  sources =
    lib.mapAttrs (_: fromMarkdown) (agentFiles ../opencode/agents ".md")
    // lib.mapAttrs (_: fromToml) (agentFiles ../codex/agents ".toml");
  adaptBody =
    lib.replaceStrings
    ["$pr-review-style" "~/.codex/skills/pr-review-style/SKILL.md"]
    ["/pr-review-style" "~/.claude/skills/pr-review-style/SKILL.md"];
  render = name: agent: ''
    ---
    name: ${builtins.toJSON name}
    description: ${builtins.toJSON agent.description}
    model: inherit
    permissionMode: default
    ${lib.optionalString agent.readOnly "disallowedTools: [Edit, Write, NotebookEdit]"}
    ---
    ${adaptBody agent.body}'';
in {
  inherit sources agentFiles;
  agents = lib.mapAttrs render sources;
}
