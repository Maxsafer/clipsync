---
name: clipsync
description: Read, list, or push items on a self-hosted clipsync server. Use
  when the user asks to fetch/read/show/pull clipsync clips, the latest clip,
  the last image, the last N clips or images, or to push text/files into
  clipsync. Authenticates via the CLIPSYNC_BASE and CLIPSYNC_TOKEN env vars.
---

# clipsync

Self-hosted clipboard relay at https://github.com/Maxsafer/clipsync. This
skill drives its REST API with curl.

## Setup check

Two env vars must be set in the user's shell:

- `CLIPSYNC_BASE` — base URL, e.g. `https://clips.example.com` (no trailing slash)
- `CLIPSYNC_TOKEN` — Bearer token from the Settings tab of the web UI

If either is missing, stop and tell the user to add them to their shell rc:

    export CLIPSYNC_BASE="https://your-clipsync-host"
    export CLIPSYNC_TOKEN="paste-token-from-settings"

Never write the token to a file inside the project.

## Authenticated curl

Every request uses the bearer header. For readability define once:

    CS_AUTH=(-H "Authorization: Bearer $CLIPSYNC_TOKEN")

…then `curl -fsS "${CS_AUTH[@]}" "$CLIPSYNC_BASE/..."`.

## Common operations

### Latest clip (raw bytes, original Content-Type)

The server's `Content-Disposition` filename includes a UTC timestamp so each
fetch is unique — just `cd /tmp` and let `curl -OJ` pick the name:

    cd /tmp && curl -fsS -OJ "${CS_AUTH[@]}" "$CLIPSYNC_BASE/api/clip/latest"

curl prints `curl: Saved to filename 'clip-<id8>-<ts>[-<name>].<ext>'` —
Read that path.

### Latest text only

    curl -fsS "${CS_AUTH[@]}" "$CLIPSYNC_BASE/api/clip/latest.txt"

(Returns 409 if the latest clip isn't text.)

### List recent clips (metadata, no blobs)

    curl -fsS "${CS_AUTH[@]}" "$CLIPSYNC_BASE/api/clips?limit=50"

Returns a JSON array, newest first. Each item:

    { id, type ("text"|"image"|"file"), mime, size, filename, device_label,
      preview, created_at }

### Last N images

1. `GET /api/clips?limit=50` and parse with `jq` for `type == "image"`.
2. Fetch each with `curl -OJ` — server-side timestamps keep names unique.

Example fetching the last 3 images:

    cd /tmp && curl -fsS "${CS_AUTH[@]}" "$CLIPSYNC_BASE/api/clips?limit=50" \
      | jq -r '[.[] | select(.type=="image")] | .[0:3] | .[].id' \
      | while read id; do
          curl -fsS -OJ "${CS_AUTH[@]}" "$CLIPSYNC_BASE/api/clip/$id"
        done

Then Read each file curl printed.

### Specific clip by ID

    cd /tmp && curl -fsS -OJ "${CS_AUTH[@]}" "$CLIPSYNC_BASE/api/clip/<id>"

Metadata only:

    curl -fsS "${CS_AUTH[@]}" "$CLIPSYNC_BASE/api/clip/<id>/meta"

### Push text into clipsync

    echo "the content" | curl -fsS "${CS_AUTH[@]}" \
      -H "Content-Type: text/plain; charset=utf-8" \
      -H "X-Device-Label: claude-code" \
      --data-binary @- \
      "$CLIPSYNC_BASE/api/clip"

### Push a file

    curl -fsS "${CS_AUTH[@]}" \
      -H "X-Device-Label: claude-code" \
      -F "file=@/path/to/file" \
      "$CLIPSYNC_BASE/api/clip"

### Delete a clip / clear all

    curl -fsS -X DELETE "${CS_AUTH[@]}" "$CLIPSYNC_BASE/api/clip/<id>"
    curl -fsS -X DELETE "${CS_AUTH[@]}" "$CLIPSYNC_BASE/api/clips"

## Conventions

- Always pass `-fsS` to curl so HTTP errors become non-zero exits and don't
  silently leave partial files on disk.
- For blob downloads use `cd /tmp && curl -OJ` — the server's
  Content-Disposition includes a UTC timestamp so repeated fetches never
  collide on disk.
- When the user says "latest" without specifying type, prefer
  `/api/clip/latest` (returns the most recent regardless of type) and Read
  the saved file — Claude Code renders images visually that way.
- Use `-H "X-Device-Label: claude-code"` on every push so the user can see in
  the web UI which clips Claude produced.
