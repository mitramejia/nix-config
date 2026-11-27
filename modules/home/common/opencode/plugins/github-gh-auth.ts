import { Plugin } from "@opencode/plugin"
import { execFile } from "node:child_process"
import { promisify } from "node:util"

const exec = promisify(execFile)

export default Plugin.define({
  id: "local.github-gh-auth",
  async setup(ctx) {
    if (process.env.GITHUB_PAT_TOKEN) return
    let token: string
    try {
      token = (await exec("gh", ["auth", "token", "--hostname", "github.com"], { timeout: 5000 })).stdout.trim()
    } catch {
      // gh errors can contain credentials in stdout/stderr. Never log them.
      return
    }
    if (!token || /\s/.test(token)) return
    await ctx.mcp.transform((editor) => {
      editor.update("github", (server) => {
        if (
          server.type !== "remote" ||
          server.disabled ||
          server.url !== "https://api.githubcopilot.com/mcp/" ||
          server.oauth !== false ||
          server.headers?.Authorization !== "Bearer "
        )
          return
        // Config substitutions run before transforms: the managed missing PAT
        // becomes exactly "Bearer ". Preserve any other authorization override.
        const authorization = Object.keys(server.headers).filter((key) => key.toLowerCase() === "authorization")
        if (authorization.length !== 1) return
        server.headers.Authorization = `Bearer ${token}`
      })
    })
  },
})
