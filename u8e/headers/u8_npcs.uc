

enum party_npcs
{
	PARTY		= -357,	//Used by several intrinsics (e.g. UI_count_objects) that would otherwise take a single NPC
						//Not supported by several other intrinsics that you'd really like it to (e.g. UI_get_cont_items)
	AVATAR			= -356

};

enum temp_npcs {
	DUPRE = -1,
	SHAMINO = -2,
	IOLO = -3,
};