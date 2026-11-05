# Function list

Total, 585 items.
Every function, method and class in the app, the connector, the scripts and `run.py`, in file order. The text after each name is the first line of its docstring, or blank when it has none.

## app/__main__.py  (3)

- `serve` (def, line 15). Run the server and return the exit code. The address is announced only once the port is really bound, so a
- `serve.announce` (def, line 21)
- `main` (def, line 42)

## app/check.py  (5)

- `_load` (def, line 25)
- `_fields` (def, line 39)
- `check` (def, line 45). Problems found, as text that holds no stored value.
- `fix` (def, line 135). Repair the one kind of damage a version of the app caused: a hidden-name entry whose value is a code such as
- `main` (def, line 156)

## app/demo.py  (4)

- `_NoHits` (class, line 21)
- `_NoHits.predict` (def, line 22)
- `seed` (def, line 26)
- `create_demo_app` (def, line 49)

## app/forms.py  (20)

- `Question` (class, line 18). One entry of a form, as it is on the Clio page. A follow-up that Clio shows only after a Yes or No is its own
- `Parsed` (class, line 132)
- `count` (def, line 141)
- `hint` (def, line 145). The short line under a question: when Clio shows it, what kind of answer it takes, how long it may be.
- `over` (def, line 164). How many characters the answer is over what the Clio box takes (0 when it fits or has no limit).
- `not_discussed` (def, line 170). True when an answer is Not discussed, with or without words after it. Such an answer leaves the Clio field empty.
- `settled` (def, line 175). True when an answer says something a follow-up can depend on: it is not empty and not Not discussed.
- `_norm` (def, line 180)
- `choice` (def, line 184). The options an answer names, as (options, exact), or None when it names none. Yes or No takes a leading Yes or
- `_is_date` (def, line 203). True for a real calendar date written as month/day/year, the one shape the Clio extension can enter.
- `choice_problem` (def, line 212). A short warning when a Yes or No, pick-one or checkbox answer is not what Clio can pick, else an empty text.
- `visibility` (def, line 225). For every entry, {number: (state, parent, reason)}. The state is always (no condition), open (the parent answer
- `strict` (def, line 252). The answers as Clio can take them, and what was changed to get there, as [(number, kind, text)]. A Yes or No
- `schema` (def, line 282). The form as plain data, for the Clio extension and for tests.
- `parse` (def, line 288). Read the answers out of a reply or a stored version. A stray [OUTPUT: ...] line is ignored.
- `render` (def, line 310). The canonical stored text: every marker in order, an empty answer where there is none.
- `merge` (def, line 315). The new answers laid over the latest version, made strict (see strict). A question the reply did not answer keeps
- `missing` (def, line 323). Question numbers with no answer.
- `rows` (def, line 328). [(number, question, answer)] for display, from a stored version.
- `numbers` (def, line 334). [2, 3, 4, 9] as "2 to 4 and 9" is not needed here, a plain list reads fine: "2, 3, 4 and 9".

## app/ids.py  (5)

- `_next_n` (def, line 13)
- `make_client_id` (def, line 20)
- `make_transcript_id` (def, line 28)
- `header_line` (def, line 33)
- `find_header` (def, line 39). Return the first valid header match in text, or None. Never guesses.

## app/outputs.py  (2)

- `is_slug` (def, line 34)
- `is_form` (def, line 38)

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
- `Rule` (class, line 36)
- `spoken_to_email` (def, line 63). 'juan dot cruz seventy one at yahoo dot com' -> 'juan.cruz71@yahoo.com'; spelled letters are joined.
- `_trim_name` (def, line 140). Drop trailing non-name words, a possessive 's, and bail if the name starts with one.
- `detect` (def, line 159)

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

## app/web/app.py  (82)

- `client_url` (def, line 44). The client page with a call selected. Only IDs, numbers and fixed words go in the address, never a value.
- `create_app` (def, line 51)
- `create_app.lifespan` (def, line 60)
- `create_app.open_store` (def, line 78)
- `create_app.guard` (def, line 84)
- `create_app.render` (def, line 109)
- `create_app.friendly_errors` (def, line 121). A person who submitted a form sees a page with a way back. Scripts keep the JSON they expect.
- `create_app.storage_errors` (def, line 137). A damaged file affects one client, so the page names it and the rest of the app keeps working.
- `create_app.call_day` (def, line 148). The call date, or ValueError. A future date is almost always a typo, and it would sort wrongly. So is
- `create_app.maybe_int` (def, line 158)
- `create_app.bad_form` (def, line 164)
- `create_app.client_or_404` (def, line 167)
- `create_app.tx_or_404` (def, line 173)
- `create_app.go` (def, line 179)
- `create_app.workspace` (def, line 182)
- `create_app.index` (def, line 199)
- `create_app.new_client` (def, line 207)
- `create_app.overview` (def, line 218). The client's page. extra can carry a notice, an error or the selected call.
- `create_app.call_rows` (def, line 230). Each call with the state of the outputs in the fixed order: received (latest version), waiting or none,
- `create_app.display_args` (def, line 249)
- `create_app.pick_view` (def, line 255). Transcript while nothing has been requested or received, otherwise Outputs, unless the address says.
- `create_app.hide_notice` (def, line 261)
- `create_app.client_context` (def, line 267). Everything the client page needs, with the call chosen by ?tx= (else the one just saved, else the newest).
- `create_app.client_page` (def, line 306)
- `create_app.archive` (def, line 345)
- `create_app.export` (def, line 352)
- `create_app.intake_form` (def, line 366)
- `create_app.flag_body` (def, line 370). The open flags for the page: the words, and (only when there are any) the places that need a choice.
- `create_app.review_extras` (def, line 378). The checklist, directions and any flagged words in them for the review page. A first review starts from the
- `create_app.hide_words` (def, line 391). Words hidden with the Hide button in the review's directions box (for this transcript only, or for the client
- `create_app.place_fields` (def, line 401). Choices for the typed places that need one, from fields "start|hide|word" or "start|send|word".
- `create_app.begin_review` (def, line 411). Scrub the pasted text for this client and show the review page, or the paste form with the problem.
- `create_app.intake_review` (def, line 432)
- `create_app.intake_new_form` (def, line 441)
- `create_app.intake_new` (def, line 445)
- `create_app.intake_start` (def, line 476)
- `create_app.client_options` (def, line 509). Save the client's scrubbing options and come back to the page they were changed on.
- `create_app.delete_counts` (def, line 539)
- `create_app.delete_client_page` (def, line 544). Asks first. Deleting is final, so the page says what goes and has one red button and a way back.
- `create_app.delete_client` (def, line 553)
- `create_app.delete_transcript_page` (def, line 562)
- `create_app.delete_transcript` (def, line 571)
- `create_app.rename_client` (def, line 581)
- `create_app.carried_decision` (def, line 591). One decision carried through a rescan, or None when it is not the shape this app writes.
- `create_app.parse_review_form` (def, line 602). Decisions and extra values from the review form, plus what earlier rescans carried forward. A carry
- `create_app.carry_json` (def, line 641)
- `create_app.intake_rescan` (def, line 645)
- `create_app.intake_directions_preview` (def, line 660). Flagged words in the directions box on the review page, for the review as it stands: the choices made so far,
- `create_app.intake_save` (def, line 677)
- `create_app.output_blocks` (def, line 711). One block for each of the 7 outputs, in the app's order (the 3 text outputs make the board, the 4 forms sit
- `create_app.output_blocks.href` (def, line 725)
- `create_app.transcript_page` (def, line 785). The call page moved into the client page. Old links land on the right call, with every version and compare
- `create_app.latest_version` (def, line 796). Only a number, so the page can notice a version saved by the connector. It counts the versions of all
- `create_app.copy_choice` (def, line 804). The ticked output slugs, the optional directions and the confirmed flagged words, from JSON
- `create_app.copy_transcript` (def, line 821)
- `create_app.request_change` (def, line 840). Copy text that asks Claude to change one output. The typed request is scrubbed first. Words the scrubber
- `create_app.json_object` (def, line 865)
- `create_app.scrub_preview` (def, line 875). The capitalized words still flagged in text typed for Claude (a change request or directions), checked the
- `create_app.hide_word` (def, line 889). Hide one flagged word in the text being sent. By default it is hidden for this transcript only: later text
- `create_app.editable` (def, line 904). The transcript and the version shown in the editor. 404 unless the output has a version to start from.
- `create_app.form_fields` (def, line 912). The edit page's boxes for a form: [(number, question, text, hint, yesno)], the text with hidden names as stored.
- `create_app.form_fields.yes_no` (def, line 918)
- `create_app.output_edit_page` (def, line 933)
- `create_app.output_edit_save` (def, line 943)
- `create_app.save_answer` (def, line 972). Save the edited answers of a form as one new version (JSON: changes {number: text}, version, or the older
- `create_app.hide_text` (def, line 1004). Hide a word, email or address in a saved call: the value joins the client's hidden names, the transcript
- `create_app.set_call_title` (def, line 1024). Set or clear the optional call title. It is stored as typed, shown on screen only and never sent to Claude.
- `create_app.outgoing_page` (def, line 1046)
- `create_app.message_input` (def, line 1050). text, kind, transcript ID and the raw fields of an outgoing message, from JSON or a form.
- `create_app.outgoing_preview` (def, line 1065)
- `create_app.outgoing_hide_word` (def, line 1080). Hide one flagged word in a message. With a transcript chosen it is hidden for that transcript only unless
- `create_app.outgoing_copy` (def, line 1095)
- `create_app.import_page` (def, line 1114). kind=summary opens the page with Running summary chosen. tx= picks the call the reply is for, and the
- `create_app.import_check` (def, line 1125)
- `create_app.import_save` (def, line 1143)
- `create_app.registry_page` (def, line 1161)
- `create_app.registry_edit` (def, line 1168)
- `create_app.wants_json` (def, line 1210)
- `create_app.settings_view` (def, line 1213)
- `create_app.settings_done` (def, line 1221). Saved in place when the page asked for JSON, else back to the page with the result shown.
- `create_app.settings_page` (def, line 1231)
- `create_app.settings_save` (def, line 1236). One section at a time: section=model saves the name finder settings, section=connector the connector switch.

## app/web/security.py  (7)

- `read_form` (def, line 16). The posted form. Starlette's defaults (one field up to 1 MB, 1000 fields) are lower than what the app accepts: a
- `host_allowed` (def, line 36)
- `Csrf` (class, line 43)
- `Csrf.__init__` (def, line 44)
- `Csrf.token` (def, line 47)
- `Csrf.valid` (def, line 50)
- `csrf_guard` (def, line 54). Dependency on every router: a state-changing request must carry the token for its session.

## app/workflow.py  (129)

- `clean_text` (def, line 28). The pasted text as the scrubber should read it. Invisible format characters (zero-width spaces, a byte
- `local_time` (def, line 37). A stored UTC timestamp as the user's own date and time. Unreadable values are shown as they are.
- `local_day` (def, line 45)
- `_same_call_text` (def, line 49). Scrubbed text with the spacing that does not change the call removed, to spot a repeated paste.
- `project_instructions` (def, line 89). The standing text for the claude.ai Project instructions box. It names the save_output tool only when the
- `ReviewIncomplete` (class, line 97). Some flagged words have no decision yet.
- `DirectionsFlagged` (class, line 101). The directions hold capitalized words that might be names. `words` are the ones not yet confirmed.
- `DirectionsFlagged.__init__` (def, line 104)
- `ImportProblem` (class, line 110). The pasted reply cannot be imported as it is. The message says what to do.
- `Settings` (class, line 120)
- `ClientOptions` (class, line 130). What is scrubbed for one client. first_names: 'inherit' uses the global setting.
- `load_client_options` (def, line 137)
- `save_client_options` (def, line 146)
- `client_settings` (def, line 158). The global settings with this client's own scrub options applied on top.
- `lone_name_is_first` (def, line 165). For a code with no part whose full form is one word: is that word a first name? The word is a surname when a
- `name_hidden` (def, line 174). (first names hidden, last names hidden) for this client. With names switched off, neither is.
- `person_pieces` (def, line 180). The pieces of one name code, as [(text, code or None)], or None when the code has no known value. A piece with a
- `hide_known_now` (def, line 209). Saved call text with every real value the client's hidden names know now replaced by its code. A name hidden
- `restore_switched_off` (def, line 222). Scrubbed call text as it should leave for Claude under this client's scrubbing options. A code of a kind switched
- `restore_switched_off.swap` (def, line 233)
- `load_settings` (def, line 248)
- `save_settings` (def, line 257)
- `apply_settings` (def, line 267)
- `scrub_config` (def, line 272)
- `segments` (def, line 278). [(text, type or None)] for the original text, given (start, end, type) spans.
- `real_segments` (def, line 291). [(text, type or None)] for the Transcript tab: each placeholder shows its real value. A value keeps its tag while
- `tag_segments` (def, line 319). [(text, type or None)] for scrubbed text: each placeholder becomes a tagged piece.
- `client_full_name` (def, line 330). The real full name of the client as seen locally: the person whose first name matches.
- `client_rows` (def, line 343)
- `Person` (class, line 357)
- `Detection` (class, line 366)
- `KnownNames` (class, line 373). What every client's hidden names say about who is who, read once for a match.
- `KnownNames.shared` (def, line 379)
- `KnownNames.staff` (def, line 382). Office staff by a mark, or stored for more than one client, which only office staff are.
- `known_names` (def, line 387)
- `office_speaker` (def, line 402). The entity that answers the calls, from the speaker lines of one call, or None when that cannot be told.
- `office_speaker.is_client` (def, line 414)
- `detect_client` (def, line 426). Look at a pasted transcript before any client is chosen. Scrubs against an empty registry, so nothing is
- `detect_client.rank` (def, line 460)
- `_client_matches` (def, line 470). Existing clients that one of these non-office people belongs to. A full-name hit is strong, unless that name
- `FlagGroup` (class, line 499)
- `Intake` (class, line 506)
- `_groups` (def, line 518)
- `is_ask` (def, line 531). The word is a name hidden for this transcript only, and also written there as plain text, so each place in the
- `ask_list` (def, line 537). The places that need a choice, for the page: [{word, code, places: [{start, end, before, after}]}].
- `open_groups` (def, line 544). The flag groups still waiting: a word ticked as written is settled, but a place that needs a choice is not
- `Plan` (class, line 552). What the reviewer decided, as the scrubber needs it.
- `place_ok` (def, line 560). A per-place span still points at the word it was chosen for. Offsets refer to the cleaned text the review page
- `plan_decisions` (def, line 567). decisions: dicts with text, decision ('scrub' or 'keep'), spans, and each=True when the choice is for those
- `run_intake` (def, line 586). Scrub the pasted transcript against a copy of the client's registry. Saves nothing. decisions: the reviewer's
- `clean_title` (def, line 609). The call title as it is stored: the text as typed, with invisible characters and extra spaces removed. A title
- `local_names` (def, line 618). Entities hidden in one transcript only: chosen place by place at review (the transcript's text holds their
- `_plain_word` (def, line 627). The word is written in the transcript as plain text, whole word and same case, outside any code.
- `local_scope` (def, line 633). (auto, ask) for text typed about one transcript. auto: names hidden in this transcript only whose word no longer
- `clean_places` (def, line 643). Choices for the places that need one, as sent by the page: [{start, word, choice}] with choice hide or send.
- `scrub_typed` (def, line 653). Scrub text typed for Claude about one transcript. scope: (auto, ask) from local_scope. kept: a function telling
- `stored_scope` (def, line 674). (auto, ask) and the Keep test for text typed about a saved transcript. Nothing for another client's or no call.
- `hide_word_ok` (def, line 682). A word to hide in a message being sent, tidied, or ImportProblem.
- `_review_scope` (def, line 694)
- `_kept_in_review` (def, line 698)
- `review_directions_groups` (def, line 703). The flag groups in directions typed on the review page, for the review as it stands now: the choices made so
- `review_directions_flags` (def, line 715)
- `_scrub_review_directions` (def, line 721). Directions typed on the review page, scrubbed like a change request against the registry this review holds
- `save_transcript` (def, line 747). Re-scrub with the reviewer's decisions and store the scrubbed result. decisions: dicts with
- `save_transcript.scrubbed_directions` (def, line 772)
- `set_title` (def, line 832). Change the call title of a saved call. Returns the stored title, which is empty when it was cleared.
- `chosen_outputs` (def, line 843). The known output slugs among the ticked values, in the app's order. Refuses none and refuses unknown ones.
- `planned_outputs` (def, line 853). The known output slugs ticked on the review page, in the app's order. None ticked is allowed there.
- `preticked_outputs` (def, line 861). What the checklist starts with: this call's last copy, else what was ticked when it was saved, else the last
- `more_ticked` (def, line 872). What the Request more outputs list on the Outputs view starts with: only the outputs asked for and still waiting.
- `prepare_directions` (def, line 878). The optional directions typed beside Copy for Claude, scrubbed like a change request. Returns the scrubbed
- `hide_for_request` (def, line 896). Hide a flagged word in text being sent. By default it is hidden for this transcript only: a transcript-only
- `copy_for_claude` (def, line 935). The text the user pastes into claude.ai. Records the copy and the ticked outputs. Refuses until the review is
- `Outgoing` (class, line 979)
- `prepare_message` (def, line 987)
- `commit_message` (def, line 1014)
- `last_change_output` (def, line 1021). The output the most recent change request for this call was about, if any.
- `change_intro` (def, line 1031). The opening of a change request: only which output it is about.
- `StaleVersion` (class, line 1036). The page was built before another version of this output was saved.
- `prepare_change_request` (def, line 1040). The text to copy when the user asks Claude to change one output. The typed request is scrubbed with the
- `short_day` (def, line 1083). A stored UTC timestamp as the user's own day and month, such as 3 Nov.
- `long_day` (def, line 1095). 2026-11-02 as 2 Nov 2026. Anything else is shown as it is.
- `OutputPiece` (class, line 1107). One output taken from a reply, checked on its own.
- `OutputPiece.name` (def, line 1119)
- `ImportCheck` (class, line 1124)
- `mask_known_values` (def, line 1147). Replace real values the registry knows with their placeholders, so the stored output never holds them.
- `placeholder_text` (def, line 1175). Stored output text as it may leave the app as placeholder text (a change request, the raw copy target, the
- `_keep_plain` (def, line 1184)
- `keep_flags` (def, line 1193). (first names, last names) that reach Claude as written for this client, so a reply that holds them is not masked
- `split_markers` (def, line 1204). The text before the first [OUTPUT: name] line, and [(name as written, section text)] for each marker.
- `strip_header_lines` (def, line 1212). Remove valid [CLIENT: .. | TX: ..] headers from an output's text and trim blank lines around what is left.
- `strip_header_lines.drop` (def, line 1215)
- `form_body` (def, line 1228). Read a form reply: (the answers it sent as marker text, {number: answer}). A reply that cannot be saved adds the
- `check_import` (def, line 1256). Check a reply before it is saved. A reply with [OUTPUT: name] lines is split into one piece per marker. One
- `check_import.piece` (def, line 1301)
- `rehydrated_segments` (def, line 1333). Pieces of rehydrated text; unknown placeholders are marked so the page can highlight them.
- `save_import` (def, line 1346). Save a checked reply. Every output in it becomes a new version in one transaction, or none does.
- `edit_output` (def, line 1382). Save a hand edit of an output as a new version. The text is placeholder text, and known real values typed into
- `same_answer` (def, line 1415). True when what a form box posts is what the page showed, so the answer was not changed. Line breaks and edge
- `edit_answers` (def, line 1424). Save a hand edit of one or more answers of a form as a new version. `changes` is {question number: text}. Every
- `HideResult` (class, line 1462)
- `claude_has_seen` (def, line 1468). The call was copied for Claude, or an output exists, so Claude has the text as it was.
- `delete_transcript` (def, line 1473). Delete one call with its outputs and the messages copied for it. Names hidden for this call only go too, unless
- `_put_back` (def, line 1496). The text with every code that resolves to this entry replaced by its real words. Codes of other entries, and
- `_put_back.swap` (def, line 1501)
- `delete_hidden_name` (def, line 1513). Delete a hidden name and put its real words back where its codes stand. Every saved call of the client gets its
- `hide_in_transcript` (def, line 1546). Hide a word in a saved call. The value joins the client's registry, every whole-word place in the transcript
- `view_output` (def, line 1592)
- `view_form` (def, line 1599). A form version for the page: (rehydrate result, [row]) where each row is one question with its answer as real
- `forms_listing` (def, line 1631). All the answers of a form as one text for Copy all: the question number and question, then the answer. An entry
- `clio_text` (def, line 1642). The text of Copy for Clio, which the Chrome extension in clio_filler reads: a header (format, form, client, call,
- `form_items` (def, line 1655). The entries of a form panel in order. Consecutive entries that Clio would not show and that hold no answer are
- `form_items.close` (def, line 1661)
- `form_counts` (def, line 1682). The numbers in the header of a form panel. `total` is the entries Clio would show now (every entry that is not
- `form_diff` (def, line 1691). The questions whose answer differs between two versions (as real text): [(number, question, diff rows)], and how
- `_bare` (def, line 1704). A word without its punctuation, so "Friday," and "Friday" count as the same word when comparing.
- `_word_marks` (def, line 1709). Two lines as [(text, changed)] pieces, with the words that differ marked, from difflib on words. A difference in
- `_word_marks.piece` (def, line 1715)
- `diff_rows` (def, line 1736). [(kind, [(text, changed)])] with kind in same / add / del. Lines that were changed rather than replaced are
- `diff_lines` (def, line 1767). [(kind, line)] with kind in same / add / del, for the version comparison.
- `transcript_name` (def, line 1779). How a call is named on screen: its title, else its date such as 3 Nov 2026.
- `registry_rows` (def, line 1784). One row per hidden name. A name hidden in one transcript only says which one ("Only in <title or date>"), found
- `save_entity_forms` (def, line 1803). Apply the edited forms of one hidden name together. values: part ('full', 'first', 'last', 'nick') -> text.
- `directions_for_display` (def, line 1818). Saved directions (stored with codes) as they are shown in the box, with real names, because Copy for Claude
- `directions_for_display.swap` (def, line 1823)
- `hidden_name_code` (def, line 1836). The code a hidden person is written as in text for Claude, such as [PERSON_3]. Empty when not hidden.
- `find_entity` (def, line 1842)
- `export_markdown` (def, line 1851). The client's history with real values restored. Handed to the browser as a download, never stored.
- `valid_ids` (def, line 1873)

## mcp_server/server.py  (5)

- `save_output` (def, line 40). Returns (message, is_error). The message never contains stored or submitted content.
- `_error` (def, line 77)
- `handle` (def, line 81). One JSON-RPC message in, one reply out (None for notifications).
- `handle.ok` (def, line 86)
- `serve` (def, line 110)

## run.py  (36)

- `Stop` (class, line 54). A problem the person can fix. The message says how.
- `say` (def, line 58)
- `venv_dir` (def, line 62)
- `venv_python` (def, line 66)
- `check_python` (def, line 71)
- `deps_digest` (def, line 84). A fingerprint of what the libraries depend on. A version bump or a new description does not change it,
- `state` (def, line 98). What the installed environment was built for.
- `read_stamp` (def, line 103)
- `write_stamp` (def, line 110)
- `environment_works` (def, line 114)
- `plan` (def, line 125). What the environment needs, as (action, reason). The actions are
- `pip_install` (def, line 149)
- `run_step` (def, line 154)
- `install` (def, line 169). Build the environment from nothing. This deletes an existing .venv.
- `upgrade` (def, line 191). Install changed requirements into the existing environment. Nothing is deleted.
- `ensure_environment` (def, line 201). Make the environment ready, doing only what is missing. Returns the action taken.
- `sha256_of` (def, line 221)
- `read_manifest` (def, line 229). (release tag, {file name: (sha256, size)}), or None when the project has no model list.
- `file_marks` (def, line 252)
- `model_verified` (def, line 256). True when the files are the ones checked before, judged by size and time alone. No hashing.
- `pip_cacert` (def, line 266). Python from python.org on macOS often lacks certificates until a post-install step is run. pip carries
- `make_opener` (def, line 281). opener(url, start) returns an open response. It starts at byte start when start is not 0.
- `make_opener.fetch` (def, line 285)
- `make_opener.opener` (def, line 292)
- `Progress` (class, line 305). One line that updates twice a second on a terminal, or a new line every 10 percent otherwise.
- `Progress.__init__` (def, line 308)
- `Progress.add` (def, line 315)
- `Progress.finish` (def, line 330)
- `download_file` (def, line 336). Fetch one file into part, continuing a partial file when the server allows it. Checks size and hash.
- `move_into_place` (def, line 381)
- `ensure_model` (def, line 392). Make sure the name model is installed and correct. Quiet and fast when it already is. A problem is
- `port_open` (def, line 446)
- `open_when_ready` (def, line 452)
- `launch` (def, line 462)
- `parse` (def, line 487)
- `main` (def, line 500)

## scripts/check_onnx_parity.py  (1)

- `main` (def, line 20)

## scripts/check_claude_reply.py  (5)

- `plain_problems` (def, line 32). Rules for every output: plain text, no dashes of the long kind, no phone numbers, only well formed placeholders.
- `text_output_problems` (def, line 50)
- `form_problems` (def, line 72)
- `check_reply` (def, line 124). Every problem in a reply, as short sentences. An empty list means the format is right.
- `main` (def, line 157)

## scripts/build_clio_forms.py  (2)

- `render` (def, line 20)
- `main` (def, line 30)

## scripts/eval_scrub.py  (1)

- `main` (def, line 22)

## scripts/export_onnx.py  (2)

- `quantize_embeddings` (def, line 16). int8 for the embedding table only. The table is two thirds of the weights. Quantizing the
- `main` (def, line 24)

## scripts/package.py  (9)

- `is_skipped` (def, line 52)
- `is_forbidden` (def, line 58)
- `collect` (def, line 63). (source file, path inside the zip, relative to the top folder).
- `sha256_of` (def, line 98)
- `write_manifest` (def, line 106). Write models/MODEL-SHA256.txt from the model files on this computer.
- `manifest_problems` (def, line 123). Differences between the manifest and the model files. Empty when they match.
- `version_of` (def, line 141)
- `build` (def, line 146)
- `main` (def, line 170)

## scripts/seed_test_cases.py  (13)

- `people` (def, line 29). A registry with the client, an office person, an email and an address. Returns it and the placeholders.
- `transcript` (def, line 40)
- `note` (def, line 48)
- `overview` (def, line 53)
- `form` (def, line 58)
- `probate` (def, line 63)
- `long_overview` (def, line 69)
- `lots_of_calls` (def, line 79). 40 calls over about four months, with titles and a mix of output states, newest first.
- `nine_versions` (def, line 95)
- `hidename_transcript` (def, line 100)
- `case_list` (def, line 105). Each case: first name, last name, calls newest first. A call is (days ago, topic, requested, outputs, status).
- `seed` (def, line 164). Add the test clients that are missing. Returns (first names added, first names skipped).
- `main` (def, line 196)

## app/web/static/app.js  (54)

- `rememberScroll` (function, line 9)
- `restoreScroll` (function, line 12)
- `say` (function, line 24)
- `reasonFor` (function, line 33)
- `legacyCopy` (function, line 39)
- `copy` (function, line 49)
- `copyLater` (function, line 57)
- `hasTyped` (function, line 65)
- `typedKey` (function, line 77)
- `forgetTyped` (function, line 80)
- `post` (function, line 85)
- `nextTheme` (function, line 94)
- `changeButton` (function, line 195)
- `flagBox` (function, line 196)
- `typedField` (function, line 197)
- `openFlags` (function, line 198)
- `refreshButton` (function, line 203)
- `confirmedWords` (function, line 218)
- `placeKey` (function, line 222)
- `placesPayload` (function, line 223)
- `mirrorPlaces` (function, line 234)
- `clientOnly` (function, line 244)
- `renderFlags` (function, line 248)
- `boxNote` (function, line 332)
- `previewReply` (function, line 340)
- `preview` (function, line 351)
- `hideWord` (function, line 369)
- `keepTyped` (function, line 403)
- `syncCopy` (function, line 439)
- `wordAt` (function, line 564)
- `snapWords` (function, line 570)
- `selectedHideText` (function, line 586)
- `guessType` (function, line 600)
- `hidePop` (function, line 607)
- `showPop` (function, line 608)
- `offerHide` (function, line 636)
- `gate` (function, line 672)
- `copiedKey` (function, line 802)
- `copiedList` (function, line 803)
- `paintCopied` (function, line 806)
- `markCopied` (function, line 812)
- `answerBox` (function, line 821)
- `picks` (function, line 822)
- `answerValue` (function, line 827)
- `answerStart` (function, line 828)
- `refreshWhen` (function, line 831)
- `dirtyRows` (function, line 840)
- `fit` (function, line 843)
- `overNote` (function, line 844)
- `refreshSave` (function, line 851)
- `saveRows` (function, line 860)
- `markClean` (function, line 870)
- `saveFailed` (function, line 878)
- `discardRows` (function, line 884)
