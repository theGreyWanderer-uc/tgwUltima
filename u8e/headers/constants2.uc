/*
 *
 *  Copyright (C) 2006-2009  The Exult Team/Team TFL
 *
 *  This program is free software; you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation; either version 2 of the License, or
 *  (at your option) any later version.
 *
 *  This program is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License
 *  along with this program; if not, write to the Free Software
 *  Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
 *
 *
 *	This header file contains several more constants used throughout usecode.
 *	Specifically, it has constants for several sprite animations and sounds, as
 *	well as some faces.
 */
 
// Title: Constants 2
// This header file defines general constants used throughout usecode, for
// Black Gate and Serpent Isle. Constants particular to a function can be
// found in the relevant codefile; constants particular to a game can be
// found in that game's header directory.
//
// *Author:* Marzo Junior (marzojr at yahoo dot com)
// with modifications by Peter M Dodge (twicescorned at gmail dot com)
//
// *Last modified:* 2009-01-31

// Enum: spite_effects
// Various sprite effect references to sprites in sprites.vga for spell effects etc.
//
// ANIMATION_BIG_BLAST			= 1  - The mother of all blast effects.
// ANIMATION_CLOUDS				= 3  - Overlay sprite for overcast cloud shadows.
// ANIMATION_MEDIUM_BLAST		= 4  - A large blast effect.
// ANIMATION_SMALL_BLAST		= 5  - A small blast effect.
// ANIMATION_TELEPORT			= 7  - Magical teleportation effect.
// ANIMATION_DEATH_VORTEX		= 8  - Effect for the death vortex spell.
// ANIMATION_POOF				   = 9  - Little poof of smoke effect to show spell failure.
// ANIMATION_FIREWORKS			= 12 - From the fireworks spell.
// ANIMATION_GREEN_BUBBLES		= 13 - Odd little green bubles sprite used as an effect.
// ANIMATION_CIRCLE_BARRIER	= 15 - Unsure?
// ANIMATION_LIGHTNING			= 17 - Lightning, from storms or spells.
// ANIMATION_BLUE_BEADS			= 18 - Odd little blue beads sprite used as an effect.
// ANIMATION_PURPLE_BUBBLES	= 21 - Odd little purple bubbles sprite used as an effect.
// ANIMATION_MUSIC				= 24 - Little musical notes, such as from music box, to indicate
// music playing visually.
enum sprite_effects
{
   ANIMATION_BIG_BLAST			= 1,
   ANIMATION_CLOUDS				= 3,
   ANIMATION_MEDIUM_BLAST		= 4,
   ANIMATION_SMALL_BLAST		= 5,
   ANIMATION_TELEPORT			= 7,
   ANIMATION_DEATH_VORTEX		= 8,
   ANIMATION_POOF				   = 9,
   ANIMATION_FIREWORKS			= 12,
   ANIMATION_GREEN_BUBBLES		= 13,
   ANIMATION_CIRCLE_BARRIER	= 15,
   ANIMATION_LIGHTNING			= 17,
   ANIMATION_BLUE_BEADS			= 18,
   ANIMATION_PURPLE_BUBBLES	= 21,
   ANIMATION_MUSIC				= 24
};

// Enum: sound_effects
// Some sound effects often referenced in usecode.  Not a complete or exhaustive
// list by any means.
//
// SOUND_BLAST					= 8  - Fireball spell sound effect.
// SOUND_BIG_BLAST			= 9  - Explosion spell sound effect.
// SOUND_MOONGATE				= 11 - Moongate raising sound effect. 00x000B
// SOUND_BOOK					= 14 - Apparently sounds like a book?  Either way, the effect
// when the book gump displays. 0x00E
// SOUND_KEY					= 27 - Sound made by keys when you use them.  "Click"
// SOUND_GLASS_SHATTER		= 37 - Glass breaking sound effect. 0x25
// SOUND_HIT					= 62 - Something getting hit in combat. 0x003E
// SOUND_TELEPORT				= 72 - Teleportation sound effect.
enum sound_effects
{
   SOUND_BLAST					= 8,
   SOUND_BIG_BLAST			= 9,
   //SOUND_MOONGATE				= 11, //Active elsehwere in my code so commented this out. 
   SOUND_BOOK					= 14,
   SOUND_KEY					= 27,
   SOUND_GLASS_SHATTER		= 37,
   SOUND_HIT					= 62,
   SOUND_TELEPORT				= 72
};

// Enum: faces
// Some faces referenced in usecode.
//
// DRACOTHRAXUS_FACE				= -293 - Unsure, too lazy to check.
// BLACK_SWORD_FACE				= -292 - Black sword graphic.
// ARCADION_GEM_FACE				= -291 - Arcadion in the soul gem.
// ARCADION_MIRROR_FACE			= -290 - Arcadion in the mirror.
// ERETHIAN_FACE					= -286 - Erethian.
enum faces
{
   DRACOTHRAXUS_FACE				= -293,
   BLACK_SWORD_FACE				= -292,
   ARCADION_GEM_FACE				= -291,
   ARCADION_MIRROR_FACE			= -290,
   ERETHIAN_FACE					= -286
};
