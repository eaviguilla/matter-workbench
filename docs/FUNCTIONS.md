# Function list

Total, 506 items.
Every function, method and class in the app, the connector, the scripts and `run.py`, in file order. The text after each name is the first line of its docstring, or blank when it has none.

## app/__main__.py  (3)

- `serve` (def, line 15). Run the server and return the exit code. The address is announced only once the port is really bound, so a
- `serve.announce` (def, line 21)
- `main` (def, line 42)

## app/check.py  (5)

- `_load` (def, line 24)
- `_fields` (def, line 38)
- `check` (def, line 44). Problems found, as text that holds no stored value.
- `fix` (def, line 130). Repair the one kind of damage a version of the app caused: a hidden-name entry whose value is a code such as
- `main` (def, line 151)

## app/demo.py  (4)

- `_NoHits` (class, line 21)
- `_NoHits.predict` (def, line 22)
- `seed` (def, line 26)
- `create_demo_app` (def, line 49)

## app/ids.py  (5)

- `_next_n` (def, line 13)
- `make_client_id` (def, line 20)
- `make_transcript_id` (def, line 28)
- `header_line` (def, line 33)
- `find_header` (def, line 39). Return the first valid header match in text, or None. Never guesses.

## app/outputs.py  (1)

- `is_slug` (def, line 30)

## app/paths.py  (8)

- `UnsafeLocation` (class, line 27). The data folder is somewhere that syncs or is tracked by Git.
- `_fold` (def, line 31)
- `_under` (def, line 35)
- `default_data_dir` (def, line 40)
- `_sync_roots` (def, line 54)
- `check_storage_location` (def, line 69). Return the resolved folder, or raise UnsafeLocation. The folder need not exist yet.
- `prepare_data_dir` (def, line 87). Check the location, create the folder owner-only and out of desktop search, and return it.
- `_exclude_from_search` (def, line 97)

## app/rehydrate.py  (2)

- `RehydrationResult` (class, line 11)
- `rehydrate` (def, line 20)

## app/scrub/evaluate.py  (7)

- `Annotated` (class, line 20)
- `load_annotated` (def, line 26)
- `load_annotated.emit` (def, line 30)
- `Report` (class, line 62)
- `Report.leaks_after_gate` (def, line 73)
- `_exempt_first` (def, line 77). With keep_first_names, a bare first name is intentionally left in plain text.
- `evaluate` (def, line 95)

## app/scrub/ner.py  (22)

- `NerUnavailable` (class, line 21). The model is not installed. Scrubbing is blocked rather than silently running rules only.
- `NerHit` (class, line 26)
- `Backend` (class, line 33)
- `Backend.predict` (def, line 34)
- `NerConfig` (class, line 38)
- `NerResult` (class, line 47)
- `find_model_file` (def, line 52)
- `NerModel` (class, line 60)
- `NerModel.__init__` (def, line 61)
- `NerModel.available` (def, line 72)
- `NerModel.loaded` (def, line 76)
- `NerModel._load` (def, line 79)
- `NerModel.detect` (def, line 90). Run the model on one piece of text (a turn). Offsets are relative to text.
- `NerModel.unload_if_idle` (def, line 105)
- `NerModel.start_reaper` (def, line 112). Background thread that frees the model when idle. Call stop_reaper() on shutdown.
- `NerModel.start_reaper.run` (def, line 114)
- `NerModel.stop_reaper` (def, line 120)
- `OnnxGlinerBackend` (class, line 128). Mirrors GLiNER's span-model preprocessing. Verified against the gliner library by
- `OnnxGlinerBackend.__init__` (def, line 132)
- `OnnxGlinerBackend.predict` (def, line 147)
- `OnnxGlinerBackend._run` (def, line 160)
- `OnnxGlinerBackend._flat` (def, line 193). Greedy non-overlapping selection by score, as GLiNER does for flat NER.

## app/scrub/parse.py  (11)

- `TranscriptFormatError` (class, line 18)
- `TranscriptFormatError.__init__` (def, line 19)
- `ParseIssue` (class, line 25)
- `Turn` (class, line 31)
- `ParsedTranscript` (class, line 41)
- `parse_transcript` (def, line 46)
- `Reading` (class, line 123)
- `_name_ok` (def, line 130)
- `_candidates` (def, line 141). Every line that could be a speaker line: (line index, name span, timestamp or None, body start, kind).
- `parse_lenient` (def, line 173)
- `norm_label` (def, line 227)

## app/scrub/pipeline.py  (25)

- `ScrubConfig` (class, line 56)
- `Applied` (class, line 63)
- `Flag` (class, line 72)
- `ScrubResult` (class, line 81)
- `ScrubResult.for_claude` (def, line 88). Header line + scrubbed text. The header is built from IDs and is never scrubbed.
- `_propagation` (def, line 93). Find every known form in the text. Returns (Span, (entity, part)) pairs.
- `local_matches` (def, line 116). (start, end, entity) for every whole-word, case-sensitive place where a name hidden in one transcript only
- `_merge` (def, line 129). Longest span first, then source priority. A span is dropped when it overlaps one already chosen. The
- `_Covered` (class, line 143). Sorted, merged intervals with a fast overlap test, for the flag pass over a long transcript.
- `_Covered.__init__` (def, line 146)
- `_Covered.hits` (def, line 155)
- `_sentence_start` (def, line 160). loose: an instruction, where a dash, bullet or semicolon also starts a new phrase ("- Next, ...").
- `_flags` (def, line 172). Capitalized words no span covers. A capitalized word in mid-sentence is always flagged
- `_learn_surnames` (def, line 199). "Denise" is known; "Denise Brooks-Hall" appears. Learn the surname.
- `_shrink_address` (def, line 216). The model's address span often runs on ("2250 Pine Ridge exit"). Cut it back to a known form.
- `_bare` (def, line 227)
- `_merge_known_part` (def, line 231). "Joy Oyelaran" where "Joy" (or "Oyelaran") is already a lone name: same person, so add the
- `_register` (def, line 245). Register a detected span. A nickname ("everybody calls me TJ") joins the speaker's entity.
- `_clean_person` (def, line 281). The model also labels pronouns, relation words and phrases as people ("I", "my father").
- `_clean_value` (def, line 296)
- `_ner_spans` (def, line 305). Model hits become spans; hits just below the threshold become review flags.
- `_scrub` (def, line 339). exact: (start, end, entity) places hidden with that entity's placeholder, whatever the registry knows.
- `_check_ner` (def, line 414)
- `scrub_transcript` (def, line 419). Scrub a call transcript. Speaker lines are used when they can be recognized. Any other layout, or none at
- `scrub_message` (def, line 436). Outgoing corrections and comments: same detection, no transcript format required. plain_requests: the text is

## app/scrub/regex_rules.py  (5)

- `has_cjk` (def, line 19)
- `Rule` (class, line 35)
- `spoken_to_email` (def, line 62). 'juan dot cruz seventy one at yahoo dot com' -> 'juan.cruz71@yahoo.com'; spelled letters are joined.
- `_trim_name` (def, line 139). Drop trailing non-name words, a possessive 's, and bail if the name starts with one.
- `detect` (def, line 158)

## app/scrub/registry.py  (37)

- `PlaceholderValue` (class, line 17). The value is, or contains, a placeholder token such as [PERSON_1].
- `has_token` (def, line 21)
- `token_spans` (def, line 25). (start, end) of every placeholder token in the text.
- `_no_token` (def, line 30)
- `norm` (def, line 35)
- `canonical_email` (def, line 39)
- `address_street` (def, line 47). '1450 Bluebonnet Trail, Unit 9, Austin, TX' -> '1450 Bluebonnet Trail'.
- `address_short` (def, line 52). '1450 Bluebonnet Trail' -> '1450 Bluebonnet' (how people say it the second time).
- `Entity` (class, line 58)
- `Entity.placeholder` (def, line 70)
- `Form` (class, line 75)
- `Registry` (class, line 82)
- `Registry.__init__` (def, line 83)
- `Registry._new` (def, line 89)
- `Registry._bind` (def, line 95)
- `Registry.lookup` (def, line 103)
- `Registry.add_person` (def, line 107)
- `Registry.add_local_person` (def, line 122). An entity for places the reviewer chose one by one. It gets a placeholder that restores, but it is not
- `Registry.make_client_wide` (def, line 137). A word hidden for one transcript only becomes a hidden name for the whole client. False when another entry
- `Registry.add_nickname` (def, line 147). Link a nickname to an existing person so both share one entity number.
- `Registry.add_surname` (def, line 157). A known single-name person is seen with a surname. Keep the bare name's placeholder
- `Registry.link_nickname` (def, line 170). "Jess" is a shorter form of "Jessica": the short entity's name becomes ent's .nick. The old
- `Registry.shorter_forms_of` (def, line 178). Entities whose lone name is a proper prefix of this first name (Jess of Jessica).
- `Registry.longer_entity_for` (def, line 185). An entity whose first name starts with this short name (Jessica for Jess), or None.
- `Registry.add_firstname` (def, line 197). A known lone surname is seen with a first name. [PERSON_n] keeps meaning the surname.
- `Registry.add_value` (def, line 206)
- `Registry.entity` (def, line 226). The entity for a placeholder. A merged duplicate resolves to the entity it was merged into.
- `Registry._unbind` (def, line 235)
- `Registry.set_form` (def, line 239). Fix the stored value of one form. Old chat text keeps its placeholders and now restores the fixed value.
- `Registry.merge` (def, line 268). dup is the same thing as keep. New text with dup's spellings gets keep's placeholder, and old
- `Registry.remove` (def, line 293). Delete an entry. Placeholders already used in earlier chat text become unknown.
- `Registry.surface` (def, line 302)
- `Registry.iter_forms` (def, line 311). Every literal form to look for in new text. Names are case-sensitive.
- `Registry.code_entries` (def, line 326). Entities that hold a placeholder token as a value: damage from an older version, which hid a code as if
- `Registry.strip_codes` (def, line 337). Remove what code_entries finds and nothing else. An entry whose full form is a code is removed (its number is
- `Registry.to_dict` (def, line 355)
- `Registry.from_dict` (def, line 365)

## app/scrub/spans.py  (2)

- `Span` (class, line 6)
- `Span.length` (def, line 14)

## app/store.py  (81)

- `Damaged` (class, line 39). A stored file cannot be read. The message names the file and never its contents.
- `Damaged.__init__` (def, line 42)
- `StoreTooNew` (class, line 47). The file was written by a newer version of the app.
- `Busy` (class, line 51). Another copy of the app or the connector kept the write lock too long.
- `_now` (def, line 55)
- `_retry` (def, line 59). Windows refuses a rename or read for a moment while a scanner or editor has the file open.
- `write_atomic` (def, line 70)
- `_read_json` (def, line 87)
- `_dump` (def, line 101)
- `_Lock` (class, line 105). One lock for all writers. The operating system releases it if the process dies, so a crash cannot leave it stuck.
- `_Lock.__init__` (def, line 108)
- `_Lock._try` (def, line 111)
- `_Lock.__enter__` (def, line 126)
- `_Lock.__exit__` (def, line 137)
- `Store` (class, line 146)
- `Store.__init__` (def, line 149)
- `Store._reset` (def, line 155)
- `Store.open` (def, line 167)
- `Store.close` (def, line 174)
- `Store.__enter__` (def, line 177)
- `Store.__exit__` (def, line 180)
- `Store._tx` (def, line 186). One transaction. Nested uses join the outer one, so a multi-step save commits or is dropped as a whole.
- `Store._step` (def, line 207)
- `Store._commit` (def, line 211)
- `Store._remove_client_folder` (def, line 235)
- `Store._remove_folder` (def, line 238)
- `Store.clean_up` (def, line 244). Remove what a crash can leave: temporary files, unlisted transcript folders, half-made client folders.
- `Store._client_dir` (def, line 270)
- `Store._client_file` (def, line 275)
- `Store._tx_dir` (def, line 278)
- `Store._client_ids` (def, line 283)
- `Store._doc` (def, line 288). The client's document, or None if there is none. Files are read afresh outside a transaction, because
- `Store._edit` (def, line 309). The document, to change inside a transaction.
- `Store._read_settings` (def, line 317)
- `Store._text` (def, line 328)
- `Store._stamp` (def, line 339)
- `Store._client_setting` (def, line 345)
- `Store.get_setting` (def, line 349)
- `Store.set_setting` (def, line 356)
- `Store.form_secret` (def, line 365). Signs form tokens. It is kept, so a page left open across a restart can still save.
- `Store._client_row` (def, line 377)
- `Store.create_client` (def, line 381). pending: made for a transcript that is not saved yet, so it is hidden until the first save.
- `Store.rename_client` (def, line 394). Change the display name only. The ID keeps its original name so earlier chats still match.
- `Store.delete_empty_client` (def, line 402). Remove a client that has no transcripts, messages or outputs, such as one made for a review that was
- `Store.delete_client` (def, line 413). Remove a client with everything it holds: transcripts, outputs, messages and the saved real values. There is
- `Store.delete_transcript` (def, line 423). Remove one transcript with its outputs and the messages copied for it. client.json stops listing it first,
- `Store.activate_client` (def, line 438)
- `Store.purge_pending` (def, line 442). Remove pending clients that never got a transcript, such as from a review that was abandoned.
- `Store._all_docs` (def, line 458)
- `Store.list_clients` (def, line 471)
- `Store.client_activity` (def, line 476). client id -> time of the latest transcript, message or output (or creation).
- `Store.get_client` (def, line 487)
- `Store.set_archived` (def, line 491)
- `Store._tx_ids` (def, line 497). Every transcript ID in use, across clients, because they are unique across clients.
- `Store._owner` (def, line 504)
- `Store._transcript_row` (def, line 516)
- `Store.add_transcript` (def, line 524)
- `Store.get_transcript` (def, line 539)
- `Store.list_transcripts` (def, line 543)
- `Store.set_transcript_status` (def, line 551)
- `Store.set_transcript_title` (def, line 559). The optional call title, already scrubbed. An empty title removes it. Titles are never sent to Claude.
- `Store.set_planned_outputs` (def, line 571). The outputs ticked on the review page, kept apart from requested_outputs (which only a copy sets).
- `Store.set_transcript_directions` (def, line 581). Directions typed for Claude, already scrubbed. Empty removes them. Sent with the next Copy for Claude.
- `Store.update_scrubbed_text` (def, line 597). Re-scrub after the reviewer's decisions. Takes scrubbed text only.
- `Store.save_registry` (def, line 607)
- `Store.load_registry` (def, line 615)
- `Store.registry_fingerprint` (def, line 619). Changes when the client's registry changes. Lets a long job notice that another writer changed it.
- `Store.find_placeholder` (def, line 624). The entity placeholder whose full form is this value.
- `Store.add_message` (def, line 636). output: the output a change request was about, so the import page can offer it.
- `Store.list_messages` (def, line 654)
- `Store._output_path` (def, line 658)
- `Store._output_versions` (def, line 663)
- `Store.add_output` (def, line 673). Add a version of one output, placeholders still in it, to that output's own file. Earlier versions stay,
- `Store.list_outputs` (def, line 694)
- `Store.set_requested_outputs` (def, line 704). The outputs ticked at the last Copy for Claude, kept in the order the app lists them.
- `Store.save_review_decision` (def, line 714)
- `Store.decided_keep` (def, line 725). The reviewer chose Keep for this word (at one place or for all) on this transcript. Only a hash of the word
- `Store.list_review_decisions` (def, line 734)
- `Store.audit` (def, line 739). Action and IDs and a byte count. Never content.
- `Store._append_audit` (def, line 749)
- `Store.list_audit` (def, line 759)

## app/web/app.py  (81)

- `client_url` (def, line 44). The client page with a call selected. Only IDs, numbers and fixed words go in the address, never a value.
- `create_app` (def, line 51)
- `create_app.lifespan` (async def, line 60)
- `create_app.open_store` (def, line 77)
- `create_app.guard` (async def, line 83)
- `create_app.render` (def, line 108)
- `create_app.friendly_errors` (async def, line 120). A person who submitted a form sees a page with a way back. Scripts keep the JSON they expect.
- `create_app.storage_errors` (async def, line 136). A damaged file affects one client, so the page names it and the rest of the app keeps working.
- `create_app.call_day` (def, line 147). The call date, or ValueError. A future date is almost always a typo, and it would sort wrongly. So is
- `create_app.maybe_int` (def, line 157)
- `create_app.bad_form` (def, line 163)
- `create_app.client_or_404` (def, line 166)
- `create_app.tx_or_404` (def, line 172)
- `create_app.go` (def, line 178)
- `create_app.workspace` (def, line 181)
- `create_app.index` (async def, line 198)
- `create_app.new_client` (async def, line 206)
- `create_app.overview` (def, line 217). The client's page. extra can carry a notice, an error or the selected call.
- `create_app.call_rows` (def, line 229). Each call with the state of the 3 outputs in the fixed order: received (latest version), waiting or none,
- `create_app.display_args` (def, line 248)
- `create_app.pick_view` (def, line 254). Transcript while nothing has been requested or received, otherwise Outputs, unless the address says.
- `create_app.hide_notice` (def, line 260)
- `create_app.client_context` (def, line 266). Everything the client page needs, with the call chosen by ?tx= (else the one just saved, else the newest).
- `create_app.client_page` (async def, line 304)
- `create_app.archive` (async def, line 343)
- `create_app.export` (async def, line 350)
- `create_app.intake_form` (async def, line 364)
- `create_app.flag_body` (def, line 368). The open flags for the page: the words, and (only when there are any) the places that need a choice.
- `create_app.review_extras` (def, line 376). The checklist, directions and any flagged words in them for the review page. A first review starts from the
- `create_app.hide_words` (def, line 389). Words hidden with the Hide button in the review's directions box (for this transcript only, or for the client
- `create_app.place_fields` (def, line 399). Choices for the typed places that need one, from fields "start|hide|word" or "start|send|word".
- `create_app.begin_review` (def, line 409). Scrub the pasted text for this client and show the review page, or the paste form with the problem.
- `create_app.intake_review` (async def, line 430)
- `create_app.intake_new_form` (async def, line 439)
- `create_app.intake_new` (async def, line 443)
- `create_app.intake_start` (async def, line 475)
- `create_app.client_options` (async def, line 503). Save the client's scrubbing options and come back to the page they were changed on.
- `create_app.delete_counts` (def, line 533)
- `create_app.delete_client_page` (async def, line 538). Asks first. Deleting is final, so the page says what goes and has one red button and a way back.
- `create_app.delete_client` (async def, line 547)
- `create_app.delete_transcript_page` (async def, line 556)
- `create_app.delete_transcript` (async def, line 565)
- `create_app.rename_client` (async def, line 575)
- `create_app.carried_decision` (def, line 585). One decision carried through a rescan, or None when it is not the shape this app writes.
- `create_app.parse_review_form` (def, line 596). Decisions and extra values from the review form, plus what earlier rescans carried forward. A carry
- `create_app.carry_json` (def, line 635)
- `create_app.intake_rescan` (async def, line 639)
- `create_app.intake_directions_preview` (async def, line 654). Flagged words in the directions box on the review page, for the review as it stands: the choices made so far,
- `create_app.intake_save` (async def, line 671)
- `create_app.output_blocks` (def, line 705). Always one block for each of the 3 outputs, in the app's order, so the board never changes shape. A block
- `create_app.output_blocks.href` (def, line 718)
- `create_app.transcript_page` (async def, line 767). The call page moved into the client page. Old links land on the right call, with every version and compare
- `create_app.latest_version` (async def, line 778). Only a number, so the page can notice a version saved by the connector. It counts the versions of all
- `create_app.copy_choice` (async def, line 786). The ticked output slugs, the optional directions and the confirmed flagged words, from JSON
- `create_app.copy_transcript` (async def, line 803)
- `create_app.request_change` (async def, line 822). Copy text that asks Claude to change one output. The typed request is scrubbed first. Words the scrubber
- `create_app.json_object` (async def, line 852)
- `create_app.scrub_preview` (async def, line 862). The capitalized words still flagged in text typed for Claude (a change request or directions), checked the
- `create_app.hide_word` (async def, line 876). Hide one flagged word in the text being sent. By default it is hidden for this transcript only: later text
- `create_app.editable` (def, line 891). The transcript and the version shown in the editor. 404 unless the output has a version to start from.
- `create_app.output_edit_page` (async def, line 900)
- `create_app.output_edit_save` (async def, line 909)
- `create_app.hide_text` (async def, line 924). Hide a word, email or address in a saved call: the value joins the client's hidden names, the transcript
- `create_app.set_call_title` (async def, line 944). Set or clear the optional call title. It is stored as typed, shown on screen only and never sent to Claude.
- `create_app.outgoing_page` (async def, line 966)
- `create_app.message_input` (async def, line 970). text, kind, transcript ID and the raw fields of an outgoing message, from JSON or a form.
- `create_app.outgoing_preview` (async def, line 985)
- `create_app.outgoing_hide_word` (async def, line 1000). Hide one flagged word in a message. With a transcript chosen it is hidden for that transcript only unless
- `create_app.outgoing_copy` (async def, line 1015)
- `create_app.import_page` (async def, line 1034). kind=summary opens the page with Running summary chosen. tx= picks the call the reply is for, and the
- `create_app.import_check` (async def, line 1045)
- `create_app.import_save` (async def, line 1063)
- `create_app.registry_page` (async def, line 1081)
- `create_app.registry_edit` (async def, line 1088)
- `create_app.instruction_rows` (def, line 1130). (slug, name, text shown in the box, starter text). A box that was never changed shows the starter text.
- `create_app.wants_json` (def, line 1135)
- `create_app.settings_view` (def, line 1138)
- `create_app.settings_done` (def, line 1146). Saved in place when the page asked for JSON, else back to the page with the result shown.
- `create_app.settings_page` (async def, line 1156)
- `create_app.settings_outputs` (async def, line 1161)
- `create_app.settings_save` (async def, line 1173). One section at a time: section=model saves the name finder settings, section=connector the connector switch.

## app/web/security.py  (7)

- `read_form` (async def, line 16). The posted form. Starlette's defaults (one field up to 1 MB, 1000 fields) are lower than what the app accepts: a
- `host_allowed` (def, line 36)
- `Csrf` (class, line 43)
- `Csrf.__init__` (def, line 44)
- `Csrf.token` (def, line 47)
- `Csrf.valid` (def, line 50)
- `csrf_guard` (async def, line 54). Dependency on every router: a state-changing request must carry the token for its session.

## app/workflow.py  (120)

- `clean_text` (def, line 26). The pasted text as the scrubber should read it. Invisible format characters (zero-width spaces, a byte
- `local_time` (def, line 35). A stored UTC timestamp as the user's own date and time. Unreadable values are shown as they are.
- `local_day` (def, line 43)
- `_same_call_text` (def, line 47). Scrubbed text with the spacing that does not change the call removed, to spot a repeated paste.
- `project_instructions` (def, line 90). The standing text for the claude.ai Project instructions box. It names the save_output tool only when the
- `copy_intro` (def, line 96). The opening of Copy for Claude. The save_output tool is mentioned only when the connector is switched on in
- `ReviewIncomplete` (class, line 103). Some flagged words have no decision yet.
- `DirectionsFlagged` (class, line 107). The directions hold capitalized words that might be names. `words` are the ones not yet confirmed.
- `DirectionsFlagged.__init__` (def, line 110)
- `ImportProblem` (class, line 116). The pasted reply cannot be imported as it is. The message says what to do.
- `Settings` (class, line 126)
- `ClientOptions` (class, line 136). What is scrubbed for one client. first_names: 'inherit' uses the global setting.
- `load_client_options` (def, line 143)
- `save_client_options` (def, line 152)
- `client_settings` (def, line 164). The global settings with this client's own scrub options applied on top.
- `lone_name_is_first` (def, line 171). For a code with no part whose full form is one word: is that word a first name? The word is a surname when a
- `name_hidden` (def, line 180). (first names hidden, last names hidden) for this client. With names switched off, neither is.
- `person_pieces` (def, line 186). The pieces of one name code, as [(text, code or None)], or None when the code has no known value. A piece with a
- `restore_switched_off` (def, line 215). Scrubbed call text as it should leave for Claude under this client's scrubbing options. A code of a kind switched
- `restore_switched_off.swap` (def, line 226)
- `load_settings` (def, line 241)
- `save_settings` (def, line 250)
- `apply_settings` (def, line 261)
- `scrub_config` (def, line 266)
- `segments` (def, line 272). [(text, type or None)] for the original text, given (start, end, type) spans.
- `real_segments` (def, line 285). [(text, type or None)] for the Transcript tab: each placeholder shows its real value. A value keeps its tag while
- `tag_segments` (def, line 311). [(text, type or None)] for scrubbed text: each placeholder becomes a tagged piece.
- `client_full_name` (def, line 322). The real full name of the client as seen locally: the person whose first name matches.
- `client_rows` (def, line 335)
- `Person` (class, line 349)
- `Detection` (class, line 358)
- `KnownNames` (class, line 365). What every client's hidden names say about who is who, read once for a match.
- `KnownNames.shared` (def, line 371)
- `KnownNames.staff` (def, line 374). Office staff by a mark, or stored for more than one client, which only office staff are.
- `known_names` (def, line 379)
- `office_speaker` (def, line 394). The entity that answers the calls, from the speaker lines of one call, or None when that cannot be told.
- `office_speaker.is_client` (def, line 406)
- `detect_client` (def, line 418). Look at a pasted transcript before any client is chosen. Scrubs against an empty registry, so nothing is
- `detect_client.rank` (def, line 452)
- `_client_matches` (def, line 462). Existing clients that one of these non-office people belongs to. A full-name hit is strong, unless that name
- `FlagGroup` (class, line 489)
- `Intake` (class, line 496)
- `_groups` (def, line 508)
- `is_ask` (def, line 521). The word is a name hidden for this transcript only, and also written there as plain text, so each place in the
- `ask_list` (def, line 527). The places that need a choice, for the page: [{word, code, places: [{start, end, before, after}]}].
- `open_groups` (def, line 534). The flag groups still waiting: a word ticked as written is settled, but a place that needs a choice is not
- `Plan` (class, line 542). What the reviewer decided, as the scrubber needs it.
- `place_ok` (def, line 550). A per-place span still points at the word it was chosen for. Offsets refer to the cleaned text the review page
- `plan_decisions` (def, line 557). decisions: dicts with text, decision ('scrub' or 'keep'), spans, and each=True when the choice is for those
- `run_intake` (def, line 576). Scrub the pasted transcript against a copy of the client's registry. Saves nothing. decisions: the reviewer's
- `clean_title` (def, line 599). The call title as it is stored: the text as typed, with invisible characters and extra spaces removed. A title
- `local_names` (def, line 608). Entities hidden in one transcript only: chosen place by place at review (the transcript's text holds their
- `_plain_word` (def, line 617). The word is written in the transcript as plain text, whole word and same case, outside any code.
- `local_scope` (def, line 623). (auto, ask) for text typed about one transcript. auto: names hidden in this transcript only whose word no longer
- `clean_places` (def, line 633). Choices for the places that need one, as sent by the page: [{start, word, choice}] with choice hide or send.
- `scrub_typed` (def, line 643). Scrub text typed for Claude about one transcript. scope: (auto, ask) from local_scope. kept: a function telling
- `stored_scope` (def, line 664). (auto, ask) and the Keep test for text typed about a saved transcript. Nothing for another client's or no call.
- `hide_word_ok` (def, line 672). A word to hide in a message being sent, tidied, or ImportProblem.
- `_review_scope` (def, line 684)
- `_kept_in_review` (def, line 688)
- `review_directions_groups` (def, line 693). The flag groups in directions typed on the review page, for the review as it stands now: the choices made so
- `review_directions_flags` (def, line 705)
- `_scrub_review_directions` (def, line 711). Directions typed on the review page, scrubbed like a change request against the registry this review holds
- `save_transcript` (def, line 737). Re-scrub with the reviewer's decisions and store the scrubbed result. decisions: dicts with
- `save_transcript.scrubbed_directions` (def, line 762)
- `set_title` (def, line 807). Change the call title of a saved call. Returns the stored title, which is empty when it was cleared.
- `output_instruction` (def, line 818). What Claude is told to produce for this output: the text saved in Settings, or the starter text.
- `save_output_instructions` (def, line 823). texts: slug -> instruction. An empty text goes back to the starter text. Instructions are sent to Claude as
- `chosen_outputs` (def, line 837). The known output slugs among the ticked values, in the app's order. Refuses none and refuses unknown ones.
- `planned_outputs` (def, line 847). The known output slugs ticked on the review page, in the app's order. None ticked is allowed there.
- `preticked_outputs` (def, line 855). What the checklist starts with: this call's last copy, else what was ticked when it was saved, else the last
- `prepare_directions` (def, line 866). The optional directions typed beside Copy for Claude, scrubbed like a change request. Returns the scrubbed
- `hide_for_request` (def, line 884). Hide a flagged word in text being sent. By default it is hidden for this transcript only: a transcript-only
- `copy_for_claude` (def, line 923). The text the user pastes into claude.ai. Records the copy and the ticked outputs. Refuses until the review is
- `Outgoing` (class, line 964)
- `prepare_message` (def, line 972)
- `commit_message` (def, line 999)
- `last_change_output` (def, line 1006). The output the most recent change request for this call was about, if any.
- `change_intro` (def, line 1024). The opening of a change request. The save_output tool is mentioned only when the connector is on.
- `StaleVersion` (class, line 1030). The page was built before another version of this output was saved.
- `prepare_change_request` (def, line 1034). The text to copy when the user asks Claude to change one output. The typed request is scrubbed with the
- `short_day` (def, line 1078). A stored UTC timestamp as the user's own day and month, such as 3 Nov.
- `long_day` (def, line 1090). 2026-11-02 as 2 Nov 2026. Anything else is shown as it is.
- `OutputPiece` (class, line 1102). One output taken from a reply, checked on its own.
- `OutputPiece.name` (def, line 1113)
- `ImportCheck` (class, line 1118)
- `mask_known_values` (def, line 1139). Replace real values the registry knows with their placeholders, so the stored output never holds them.
- `placeholder_text` (def, line 1167). Stored output text as it may leave the app as placeholder text (a change request, the raw copy target, the
- `_keep_plain` (def, line 1176)
- `keep_flags` (def, line 1185). (first names, last names) that reach Claude as written for this client, so a reply that holds them is not masked
- `split_markers` (def, line 1196). The text before the first [OUTPUT: name] line, and [(name as written, section text)] for each marker.
- `strip_header_lines` (def, line 1204). Remove valid [CLIENT: .. | TX: ..] headers from an output's text and trim blank lines around what is left.
- `strip_header_lines.drop` (def, line 1207)
- `check_import` (def, line 1220). Check a reply before it is saved. A reply with [OUTPUT: name] lines is split into one piece per marker. One
- `check_import.piece` (def, line 1265)
- `rehydrated_segments` (def, line 1293). Pieces of rehydrated text; unknown placeholders are marked so the page can highlight them.
- `save_import` (def, line 1306). Save a checked reply. Every output in it becomes a new version in one transaction, or none does.
- `edit_output` (def, line 1330). Save a hand edit of an output as a new version. The text is placeholder text, and known real values typed into
- `HideResult` (class, line 1354)
- `claude_has_seen` (def, line 1360). The call was copied for Claude, or an output exists, so Claude has the text as it was.
- `delete_transcript` (def, line 1365). Delete one call with its outputs and the messages copied for it. Names hidden for this call only go too, unless
- `_put_back` (def, line 1388). The text with every code that resolves to this entry replaced by its real words. Codes of other entries, and
- `_put_back.swap` (def, line 1393)
- `delete_hidden_name` (def, line 1405). Delete a hidden name and put its real words back where its codes stand. Every saved call of the client gets its
- `hide_in_transcript` (def, line 1438). Hide a word in a saved call. The value joins the client's registry, every whole-word place in the transcript
- `view_output` (def, line 1484)
- `_bare` (def, line 1494). A word without its punctuation, so "Friday," and "Friday" count as the same word when comparing.
- `_word_marks` (def, line 1499). Two lines as [(text, changed)] pieces, with the words that differ marked, from difflib on words. A difference in
- `_word_marks.piece` (def, line 1505)
- `diff_rows` (def, line 1526). [(kind, [(text, changed)])] with kind in same / add / del. Lines that were changed rather than replaced are
- `diff_lines` (def, line 1557). [(kind, line)] with kind in same / add / del, for the version comparison.
- `transcript_name` (def, line 1569). How a call is named on screen: its title, else its date such as 3 Nov 2026.
- `registry_rows` (def, line 1574). One row per hidden name. A name hidden in one transcript only says which one ("Only in <title or date>"), found
- `save_entity_forms` (def, line 1593). Apply the edited forms of one hidden name together. values: part ('full', 'first', 'last', 'nick') -> text.
- `directions_for_display` (def, line 1608). Saved directions (stored with codes) as they are shown in the box, with real names, because Copy for Claude
- `directions_for_display.swap` (def, line 1613)
- `hidden_name_code` (def, line 1626). The code a hidden person is written as in text for Claude, such as [PERSON_3]. Empty when not hidden.
- `find_entity` (def, line 1632)
- `export_markdown` (def, line 1641). The client's history with real values restored. Handed to the browser as a download, never stored.
- `valid_ids` (def, line 1663)

## mcp_server/server.py  (4)

- `save_output` (def, line 38). Returns (message, is_error). The message never contains stored or submitted content.
- `handle` (def, line 73). One JSON-RPC message in, one reply out (None for notifications).
- `handle.ok` (def, line 78)
- `serve` (def, line 96)

## run.py  (18)

- `Stop` (class, line 41). A problem the person can fix. The message says how.
- `say` (def, line 45)
- `venv_dir` (def, line 49)
- `venv_python` (def, line 53)
- `check_python` (def, line 58)
- `state` (def, line 69). What the installed environment was built for. If any of it changes, the install is redone.
- `read_stamp` (def, line 75)
- `environment_works` (def, line 82)
- `install_needed` (def, line 94). None when the environment is ready, else a short reason.
- `sha256_of` (def, line 106)
- `verify_files` (def, line 114). Check every file listed in CHECKSUMS.txt. Returns how many were checked. No list means no check.
- `run_step` (def, line 134)
- `install` (def, line 144)
- `port_open` (def, line 171)
- `open_when_ready` (def, line 177)
- `launch` (def, line 187)
- `parse` (def, line 210)
- `main` (def, line 223)

## scripts/check_onnx_parity.py  (1)

- `main` (def, line 20)

## scripts/eval_scrub.py  (1)

- `main` (def, line 22)

## scripts/export_onnx.py  (2)

- `quantize_embeddings` (def, line 16). int8 for the embedding table only. The table is two thirds of the weights. Quantizing the
- `main` (def, line 24)

## scripts/package.py  (7)

- `is_skipped` (def, line 132)
- `is_forbidden` (def, line 138)
- `collect` (def, line 143). (source file, path inside the zip, relative to the top folder).
- `sha256_of` (def, line 171)
- `version_of` (def, line 179)
- `build` (def, line 184)
- `main` (def, line 210)

## scripts/seed_test_cases.py  (12)

- `people` (def, line 28). A registry with the client, an office person, an email and an address. Returns it and the placeholders.
- `transcript` (def, line 39)
- `note` (def, line 47)
- `overview` (def, line 52)
- `form` (def, line 57)
- `long_overview` (def, line 62)
- `lots_of_calls` (def, line 72). 40 calls over about four months, with titles and a mix of output states, newest first.
- `nine_versions` (def, line 88)
- `hidename_transcript` (def, line 93)
- `case_list` (def, line 98). Each case: first name, last name, calls newest first. A call is (days ago, topic, requested, outputs, status).
- `seed` (def, line 156). Add the test clients that are missing. Returns (first names added, first names skipped).
- `main` (def, line 188)

## app/web/static/app.js  (35)

- `rememberScroll` (function, line 9)
- `restoreScroll` (function, line 12)
- `say` (function, line 24)
- `reasonFor` (function, line 33)
- `legacyCopy` (function, line 39)
- `copy` (function, line 49)
- `copyLater` (function, line 57)
- `hasTyped` (function, line 65)
- `post` (function, line 71)
- `nextTheme` (function, line 80)
- `changeButton` (function, line 166)
- `flagBox` (function, line 167)
- `typedField` (function, line 168)
- `openFlags` (function, line 169)
- `refreshButton` (function, line 174)
- `confirmedWords` (function, line 189)
- `placeKey` (function, line 193)
- `placesPayload` (function, line 194)
- `mirrorPlaces` (function, line 205)
- `clientOnly` (function, line 215)
- `renderFlags` (function, line 219)
- `boxNote` (function, line 303)
- `previewReply` (function, line 311)
- `preview` (function, line 322)
- `hideWord` (function, line 340)
- `keepTyped` (function, line 374)
- `syncCopy` (function, line 410)
- `wordAt` (function, line 508)
- `snapWords` (function, line 514)
- `selectedHideText` (function, line 530)
- `guessType` (function, line 544)
- `hidePop` (function, line 551)
- `showPop` (function, line 552)
- `offerHide` (function, line 580)
- `gate` (function, line 616)
