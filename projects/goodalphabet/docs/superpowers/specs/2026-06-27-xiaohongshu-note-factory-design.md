# Xiaohongshu Note Factory Design

## Context

GOODALPHABET is an AI vocabulary learning product with existing wordbooks, daily word lists, AI-generated reading passages, translation, text-to-speech, review, progress tracking, and an admin area. The growth goal is to continuously produce interesting Xiaohongshu notes that use timely topics and naturally include vocabulary, so the content can promote the product without reading like low-quality ads.

The first version will be an internal operations tool. It will generate, save, and review note drafts for human publishing. It will not automate Xiaohongshu login, posting, commenting, messaging, or engagement.

## Goals

- Generate many Xiaohongshu-ready note drafts from existing vocabulary data.
- Make each note interesting enough to stand alone as content, not just an ad.
- Naturally embed vocabulary and short explanations inside each note.
- Lightly demonstrate the product value: AI turns vocabulary into stories, short texts, dialogues, or memorable contexts.
- Preserve a history of generated notes, review decisions, publishing links, and performance metrics.
- Build a data loop so successful topics, templates, and wordbook combinations can be repeated later.

## Non-Goals

- Automatic Xiaohongshu publishing.
- Automatic account login, scraping, commenting, liking, private messaging, or following.
- Full image generation or Canva/Figma automation in the first version.
- Fully automated hot topic discovery in the first version.
- A recommendation algorithm for future content generation.

## Recommended First Version

Build an admin page named `小红书笔记工厂` under the existing admin surface. An operator uses a form to generate a batch of note drafts. The system samples vocabulary from the selected wordbook, calls the AI generation backend with structured constraints, stores the batch and notes, and displays each note for review.

The operator manually edits, approves, rejects, copies, and publishes notes on Xiaohongshu. After publishing, the operator records the Xiaohongshu link and basic performance metrics.

## User Workflow

1. Open the admin note factory page.
2. Choose a wordbook or language track, such as GRE, CET4, CET6, IELTS, TOEFL, or JLPT.
3. Choose a content scene, such as exam anxiety, workplace English, studying abroad, relationship chat, trending memes, TV/movie language, travel, comedy reversal, or Japanese drama/anime.
4. Enter a topic or trend manually, such as `暑假逆袭`, `考前崩溃`, `打工人英语`, or `日剧台词学习`.
5. Choose a style: resonance, comedy, practical tips, story, contrast, or list.
6. Choose generation count and vocabulary count per note. Defaults: 10 notes, 5 words per note.
7. Generate the batch.
8. Review each candidate note and set status to approved, needs edit, rejected, or published.
9. Copy approved content to Xiaohongshu manually.
10. Record the Xiaohongshu link and performance metrics after publishing.

## Content Output Shape

Each generated note must be stored as structured JSON with these fields:

- `titles`: 3 to 5 Xiaohongshu-style title options.
- `body`: the main note body, ready to copy after human review.
- `vocabulary`: the embedded words, definitions, and example or memory hooks.
- `cover_text`: short cover text suitable for an image.
- `image_prompt`: a prompt for future AI image or design generation.
- `hashtags`: 10 to 15 Xiaohongshu tags.
- `cta`: a light product mention or call to action.
- `quality_notes`: AI self-check notes for the operator.
- `risk_flags`: possible issues such as hard-sell language, exaggerated promises, repetitive openings, or unnatural vocabulary insertion.

## Content Templates

The first version should include these template families:

- Trending topic: borrow a current or manually entered hot topic and connect it to vocabulary learning.
- Resonance story: start from study anxiety, procrastination, exam pressure, or daily frustration.
- Comedy reversal: use a short joke or reversal to make words memorable.
- Workplace rescue: use meetings, email, interviews, reporting, and office scenes.
- TV/movie line: explain vocabulary through a scene inspired by film, TV, anime, or drama watching.
- Exam sprint: focus on high-frequency words for GRE, IELTS, TOEFL, CET, or JLPT.
- Japanese watching: connect JLPT vocabulary with Japanese drama, anime, and daily conversation.
- AI learning method: show how AI transforms word lists into stories, dialogues, or reading passages.

## Quality Rules

The generation prompt must enforce these rules:

- Every note needs a clear life scene, emotion, problem, or story hook.
- Vocabulary must appear naturally inside the note, not as a pasted word list.
- The product mention must be light and truthful.
- Avoid exaggerated claims such as guaranteed score improvement, guaranteed exam success, official endorsement, or impossible time-based promises.
- Avoid highly repetitive openings and title structures within the same batch.
- The body should sound like a human Xiaohongshu note, not a system explanation or SEO article.
- Notes should be useful even if the reader does not click through to the product.
- Each note should make the vocabulary memorable through context, contrast, humor, example sentences, or micro-stories.

## Platform Risk Boundary

The tool is only a drafting and operations aid. It should not include behavior that automates Xiaohongshu publishing or engagement. Human review is required before posting. When a note is used for explicit commercial collaboration or paid promotion, the operator is responsible for following Xiaohongshu's current commercial content and disclosure requirements.

## Data Model

### `xhs_note_batches`

Fields:

- `id`
- `created_at`
- `created_by`
- `wordbook_id`
- `language`
- `scene`
- `topic`
- `style`
- `note_count`
- `words_per_note`
- `generation_prompt`
- `status`
- `error_message`

Status values:

- `generating`
- `completed`
- `failed`

### `xhs_notes`

Fields:

- `id`
- `batch_id`
- `created_at`
- `updated_at`
- `status`
- `selected_title`
- `titles_json`
- `body`
- `vocabulary_json`
- `cover_text`
- `image_prompt`
- `hashtags_json`
- `cta`
- `quality_notes_json`
- `risk_flags_json`
- `published_url`
- `published_at`
- `views`
- `likes`
- `favorites`
- `comments`
- `profile_visits`
- `product_visits`
- `operator_notes`

Status values:

- `draft`
- `needs_edit`
- `approved`
- `published`
- `rejected`

## Backend Design

Add a focused Xiaohongshu content module. It should reuse the existing database connection and wordbook data rather than introducing a separate content store.

Core responsibilities:

- List available wordbooks.
- Sample words from a wordbook.
- Build a generation prompt from selected scene, topic, style, words, and product positioning.
- Call the existing AI provider path used elsewhere in the product when possible.
- Parse structured JSON output.
- Persist batches and notes.
- Update note status and publishing metrics.

Proposed API surface:

- `GET /api/admin/xhs/options`
  - Returns wordbooks, scenes, styles, and defaults.
- `POST /api/admin/xhs/batches`
  - Creates a batch and generates notes.
- `GET /api/admin/xhs/batches`
  - Lists recent batches.
- `GET /api/admin/xhs/batches/{batch_id}`
  - Returns a batch with notes.
- `PATCH /api/admin/xhs/notes/{note_id}`
  - Updates status, selected title, body, metadata, publishing link, or metrics.

## Frontend Design

Add an admin page at `/admin/xhs`.

Main regions:

- Generation form: wordbook, scene, topic, style, note count, words per note, generate button.
- Batch list: recent generation batches and their status.
- Note grid: generated drafts with title options, status, quick copy actions, and risk flags.
- Detail panel: full note body, vocabulary list, hashtags, cover text, image prompt, CTA, and editable publishing metrics.

The UI should be dense and operational, matching an admin tool rather than a marketing page. It should prioritize scanning, comparison, editing, and copying.

## Prompt Contract

The backend should request JSON only. If the model returns invalid JSON, the backend should surface a clear error and store the failed batch status.

Expected top-level shape:

```json
{
  "notes": [
    {
      "titles": ["title 1", "title 2", "title 3"],
      "body": "note body",
      "vocabulary": [
        {
          "word": "example",
          "definition": "definition",
          "usage": "usage or memory hook"
        }
      ],
      "cover_text": "cover text",
      "image_prompt": "image prompt",
      "hashtags": ["tag1", "tag2"],
      "cta": "light CTA",
      "quality_notes": ["quality note"],
      "risk_flags": ["risk flag"]
    }
  ]
}
```

## Error Handling

- If the wordbook has no available words, the API returns a clear validation error.
- If AI generation fails, the batch is saved as `failed` with `error_message`.
- If AI output is not valid JSON, the batch is saved as `failed` and the raw error is not shown directly to end users.
- If generated note count differs from requested count, save valid notes and show a warning.
- If a metrics update has non-numeric values, reject the update with validation errors.

## Testing Strategy

- Unit test word sampling and prompt input construction.
- Unit test JSON parsing and validation of AI output.
- API test batch creation with a mocked AI response.
- API test note status and metrics updates.
- Frontend smoke test that the admin page can render options, submit a generation request, and display returned notes.

## First-Version Acceptance Criteria

- An admin can input a topic and generation parameters.
- The system samples vocabulary from existing wordbook data.
- The system generates multiple Xiaohongshu note drafts in one batch.
- Each note includes titles, body, vocabulary explanation, hashtags, cover text, image prompt, and a light CTA.
- Generated notes are saved and can be viewed later.
- Note status can be changed between draft, needs edit, approved, published, and rejected.
- Published notes can store Xiaohongshu link and performance metrics.
- The first version contains no automatic Xiaohongshu publishing or automated engagement behavior.

## Future Extensions

- Daily scheduled draft generation.
- Manual hot topic library and performance-based topic reuse.
- AI image generation or Canva/Figma design handoff.
- Template scoring based on saved metrics.
- User-facing share note generation after completing a learning session.
- Content calendar and publishing reminders.
