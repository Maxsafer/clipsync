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

    curl -fsS "${CS_AUTH[@]}" -o /tmp/clipsync-latest "$CLIPSYNC_BASE/api/clip/latest"

Check the `Content-Type` to know what you got back. For text, just read it.
For images, rename to `/tmp/clipsync-latest.png` (or `.jpg`, matching the
mime) so the Read tool renders it visually instead of dumping bytes.

### Latest text only

    curl -fsS "${CS_AUTH[@]}" "$CLIPSYNC_BASE/api/clip/latest.txt"

(Returns 409 if the latest clip isn't text.)

### List recent clips (metadata, no blobs)

    curl -fsS "${CS_AUTH[@]}" "$CLIPSYNC_BASE/api/clips?limit=50"

Returns a JSON array, newest first. Each item:

    { id, type ("text"|"image"|"file"), mime, size, filename, device_label,
      preview, created_at }

### Last N images

1. `GET /api/clips?limit=50` and parse with `jq`.
2. Filter where `type == "image"`, take the first N.
3. For each, download to `/tmp/clipsync-<id>.<ext>` using the mime
   (`image/png` → `.png`, `image/jpeg` → `.jpg`, etc.) so Read renders them.

Example fetching the last 3 images:

    curl -fsS "${CS_AUTH[@]}" "$CLIPSYNC_BASE/api/clips?limit=50" \
      | jq -r '[.[] | select(.type=="image")] | .[0:3]
               | .[] | "\(.id) \(.mime)"' \
      | while read id mime; do
          ext=$(echo "$mime" | sed 's|image/||; s|jpeg|jpg|')
          curl -fsS "${CS_AUTH[@]}" -o "/tmp/clipsync-$id.$ext" \
               "$CLIPSYNC_BASE/api/clip/$id"
          echo "saved /tmp/clipsync-$id.$ext"
        done

Then Read each saved file.

### Specific clip by ID

    curl -fsS "${CS_AUTH[@]}" -o /tmp/clipsync-<id>.<ext> \
         "$CLIPSYNC_BASE/api/clip/<id>"

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
- When fetching images for the user to see, save with a real image extension
  and Read the file — Claude Code renders the image visually that way.
- When the user says "latest" without specifying type, prefer
  `/api/clip/latest` (returns the most recent regardless of type) and then
  branch on the response's Content-Type.
- Use `-H "X-Device-Label: claude-code"` on every push so the user can see in
  the web UI which clips Claude produced.
