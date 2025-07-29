// necromancyKeyCaretaker.uc
// Handle Necromancy Talisman creation via Key of the Caretaker
// Modified to support creating multiple talismans based on complete reagent sets
// Fixed invalid 'or' syntax in reagent counting logic

void necromancyKeyCaretaker shape#(937) () {
    UI_error_message("------------------------------------");
    UI_error_message("Function started for shape 937.");

    if (event == DOUBLECLICK) {
        UI_error_message("Double-click event triggered for Key of the Caretaker.");

        // Set test spell flag to learned
        if (!gflags[LEARNED_DEATH_SPEAK_SPELL]) {
            gflags[LEARNED_DEATH_SPEAK_SPELL] = true;
        }

        // Check the frame of the Key of the Caretaker
        var necromancyFrame = UI_get_item_frame(item);
        UI_error_message("Key of the Caretaker frame: " + necromancyFrame);

        if (necromancyFrame == 0) {
            UI_error_message("Frame 0 detected - proceeding.");

            // Prompt the player to select a container
            var selected = UI_click_on_item();
            UI_error_message("Selected item: " + selected[1]);

            if (selected[1]) {
                UI_error_message("Selected item shape: " + selected[1]->get_item_shape());
            } else {
                UI_error_message("Selected item shape: none");
            }

            if (selected[1] && selected[1]->get_item_shape() == SHAPE_BAG) {
                UI_error_message("Valid container selected: SHAPE_BAG.");
                var container = selected[1];

                // Get all items and reagents in the container
                var all_items = container->get_cont_items(SHAPE_ANY, QUALITY_ANY, FRAME_ANY);
                var reagents = container->get_cont_items(SHAPE_U8E_REAGENT, QUALITY_ANY, FRAME_ANY);
                UI_error_message("Total items in container: " + UI_get_array_size(all_items));
                UI_error_message("Reagents in container: " + UI_get_array_size(reagents));

                // Ensure the container contains only reagents
                if (UI_get_array_size(all_items) != UI_get_array_size(reagents)) {
                    UI_error_message("Container contains non-reagent items.");
                    UI_item_say(AVATAR, "Nay, it would prove vain.");
                } else {
                    UI_error_message("Container contains only reagents.");

                    // Map reagent frames to names for debugging
                    var reagent_names = [];
                    reagent_names[FRAME_NECROMANCY_DIRT] = "Dirt";
                    reagent_names[FRAME_NECROMANCY_BLACKMOOR] = "Blackmoor";
                    reagent_names[FRAME_NECROMANCY_EXECUTIONHOOD] = "Executioner's Hood";
                    reagent_names[FRAME_NECROMANCY_BONES] = "Bones";
                    reagent_names[FRAME_NECROMANCY_WOOD] = "Wood";
                    reagent_names[FRAME_NECROMANCY_BLOOD] = "Blood";
                    reagent_names[FRAME_NECROMANCY_DEADMANELBOW] = "Dead Man's Elbow";

                    // Collect reagent frames and their counts
                    var frame_counts = [];
                    for (reagent in reagents) {
                        var frame = reagent->get_item_frame();
                        if (!frame_counts[frame]) {
                            frame_counts[frame] = 0;
                        }
                        frame_counts[frame] = frame_counts[frame] + 1;
                        UI_error_message("Counted reagent: " + reagent_names[frame] + " (frame " + frame + "), count: " + frame_counts[frame]);
                    }

                    var frames_str = "";
                    var frame_idx;
                    for (frame_idx in frame_counts) {
                        if (reagent_names[frame_idx]) {
                            frames_str = frames_str + reagent_names[frame_idx] + " (" + frame_idx + ": " + frame_counts[frame_idx] + "), ";
                        }
                    }
                    UI_error_message("All reagent frames collected: [" + frames_str + "]");

                    // Map spell indices to names for debugging
                    var spell_names = [
                        "Death Speak",
                        "Mask of Death",
                        "Rock Flesh",
                        "Summon Dead",
                        "Grant Peace",
                        "Withstand Death",
                        "Create Golem",
                        "Open Ground",
                        "Call Quake"
                    ];

                    // Define spell data
                    var spell_flags = [
                        LEARNED_DEATH_SPEAK_SPELL,
                        LEARNED_MASK_OF_DEATH_SPELL,
                        LEARNED_ROCK_FLESH_SPELL,
                        LEARNED_SUMMON_DEAD_SPELL,
                        LEARNED_GRANT_PEACE_SPELL,
                        LEARNED_WITHSTAND_DEATH_SPELL,
                        LEARNED_CREATE_GOLEM_SPELL,
                        LEARNED_OPEN_GROUND_SPELL,
                        LEARNED_CALL_QUAKE_SPELL
                    ];

                    var talisman_frames = [
                        FRAME_NECROMANCY_DEATHSPEAK,
                        FRAME_NECROMANCY_MASKDEATH,
                        FRAME_NECROMANCY_ROCKFLESH,
                        FRAME_NECROMANCY_SUMMONDEAD,
                        FRAME_NECROMANCY_GRANTPEACE,
                        FRAME_NECROMANCY_WITHSTANDDEATH,
                        FRAME_NECROMANCY_CREATEGOLEM,
                        FRAME_NECROMANCY_OPENGROUND,
                        FRAME_NECROMANCY_CALLQUAKE
                    ];

                    // Define words of power for each spell
                    var words_of_power = [
                        "Kal Wis Corp",      // Death Speak
                        "Quas Corp",         // Mask of Death
                        "Rel Sanct Ylem",    // Rock Flesh
                        "Kal Corp Xen",      // Summon Dead
                        "In Vas Corp",       // Grant Peace
                        "Vas An Corp",       // Withstand Death
                        "In Oort Ylem Xen",  // Create Golem
                        "Des Por Ylem",      // Open Ground
                        "Kal Vas Ylem Por"   // Call Quake
                    ];

                    // Define required reagents for each spell
                    var spell_requirements = [];
                    spell_requirements[1] = [FRAME_NECROMANCY_BLOOD, FRAME_NECROMANCY_BONES];
                    spell_requirements[2] = [FRAME_NECROMANCY_WOOD, FRAME_NECROMANCY_EXECUTIONHOOD];
                    spell_requirements[3] = [FRAME_NECROMANCY_WOOD, FRAME_NECROMANCY_DIRT];
                    spell_requirements[4] = [FRAME_NECROMANCY_BLOOD, FRAME_NECROMANCY_BONES, FRAME_NECROMANCY_WOOD];
                    spell_requirements[5] = [FRAME_NECROMANCY_EXECUTIONHOOD, FRAME_NECROMANCY_BLACKMOOR];
                    spell_requirements[6] = [FRAME_NECROMANCY_WOOD, FRAME_NECROMANCY_DIRT, FRAME_NECROMANCY_BLACKMOOR];
                    spell_requirements[7] = [FRAME_NECROMANCY_BLOOD, FRAME_NECROMANCY_BONES, FRAME_NECROMANCY_WOOD, FRAME_NECROMANCY_DIRT, FRAME_NECROMANCY_BLACKMOOR];
                    spell_requirements[8] = [FRAME_NECROMANCY_BLOOD, FRAME_NECROMANCY_BLACKMOOR];
                    spell_requirements[9] = [FRAME_NECROMANCY_DIRT, FRAME_NECROMANCY_BONES, FRAME_NECROMANCY_WOOD, FRAME_NECROMANCY_BLACKMOOR];

                    // Find matching spells and count sets
                    UI_error_message("Starting spell matching process.");
                    var matched_spell = -1;
                    var set_counts = [];
                    var i = 1;
                    while (i <= 9) {
                        UI_error_message("Checking spell: " + spell_names[i] + " (index " + i + ", flag: " + spell_flags[i] + ")");
                        var req = spell_requirements[i];
                        var req_count = UI_get_array_size(req);

                        var req_names = [];
                        for (frame in req) {
                            UI_error_message("Required reagent: " + frame + " (" + reagent_names[frame] + ")");
                            req_names = req_names & [reagent_names[frame]];
                        }
                        var req_names_str = "";
                        var j = 1;
                        while (j <= UI_get_array_size(req_names)) {
                            req_names_str = req_names_str + req_names[j];
                            if (j < UI_get_array_size(req_names)) {
                                req_names_str = req_names_str + ", ";
                            }
                            j = j + 1;
                        }
                        UI_error_message("Required reagents for " + spell_names[i] + ": [" + req_names_str + "] (count: " + req_count + ")");

                        // Count how many complete sets are available
                        var min_sets = 9999; // Large number to find minimum
                        for (frame in req) {
                            var available = frame_counts[frame];
                            if (!available) {
                                available = 0;
                            }
                            UI_error_message("Checking frame " + frame + " (" + reagent_names[frame] + "), available: " + available);
                            if (available < min_sets) {
                                min_sets = available;
                            }
                        }
                        if (min_sets > 0) {
                            UI_error_message("Found " + min_sets + " complete sets for " + spell_names[i]);
                            set_counts[i] = min_sets;
                            matched_spell = i;
                        } else {
                            UI_error_message("No complete sets for " + spell_names[i]);
                        }
                        i = i + 1;
                    }

                    UI_error_message("Matched spell index: " + matched_spell);
                    if (matched_spell != -1) {
                        UI_error_message("Matched spell: " + spell_names[matched_spell]);
                    } else {
                        UI_error_message("No spell matched.");
                    }

                    // Process the matched spell
                    if (matched_spell != -1) {
                        var flag = spell_flags[matched_spell];
                        UI_error_message("Checking spell flag for " + spell_names[matched_spell] + " (" + flag + "): " + gflags[flag]);
                        if (gflags[flag]) {
                            UI_error_message("Spell " + spell_names[matched_spell] + " is learned. Creating " + set_counts[matched_spell] + " talisman(s).");
                            var talisman_count = set_counts[matched_spell];
                            var req = spell_requirements[matched_spell];

                            // Remove reagents for each set
                            var k = 1;
                            while (k <= talisman_count) {
                                for (frame in req) {
                                    var reagent = container->find_object(SHAPE_U8E_REAGENT, QUALITY_ANY, frame);
                                    if (reagent) {
                                        UI_error_message("Removing reagent: " + frame + " (" + reagent_names[frame] + ") for set " + k);
                                        reagent->remove_item();
                                    } else {
                                        UI_error_message("Error: Reagent " + reagent_names[frame] + " not found for set " + k);
                                    }
                                }
                                k = k + 1;
                            }

                            // Create talismans
                            k = 1;
                            while (k <= talisman_count) {
                                var talisman_frame = talisman_frames[matched_spell];
                                UI_error_message("Creating talisman " + k + " with frame: " + talisman_frame + " for spell " + spell_names[matched_spell]);
                                var talisman = UI_create_new_object(SHAPE_U8E_TALISMAN);
                                UI_error_message("Talisman created: " + talisman);
                                talisman->set_item_frame(talisman_frame);
                                UI_error_message("Talisman frame set to: " + talisman_frame);
                                UI_give_last_created(container);
                                UI_error_message("Talisman " + k + " for " + spell_names[matched_spell] + " placed in container.");
                                k = k + 1;
                            }
                            UI_item_say(AVATAR, words_of_power[matched_spell]);
                        } else {
                            UI_error_message("Spell " + spell_names[matched_spell] + " not learned.");
                            UI_item_say(AVATAR, "I lack the knowledge.");
                        }
                    } else {
                        UI_error_message("No matching spell found.");
                        UI_item_say(AVATAR, "Alas, 'tis failure.");
                    }
                }
            } else {
                UI_error_message("Invalid selection: not a container.");
                UI_item_say(AVATAR, "Nay, it would prove vain.");
            }
            UI_close_gumps();
            UI_error_message("Function completed.");
        } else {
            UI_error_message("Invalid frame for Key of the Caretaker: " + necromancyFrame);
        }
    } else {
        UI_error_message("Invalid event: " + event);
    }
    // Unset test spell flag from learned
    if (gflags[LEARNED_DEATH_SPEAK_SPELL]) {
        gflags[LEARNED_DEATH_SPEAK_SPELL] = false;
    }
    UI_error_message("------------------------------------");
}