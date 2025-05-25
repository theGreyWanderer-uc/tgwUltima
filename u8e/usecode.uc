//Tells the compiler the game type
#game "serpentisle"

//Starts autonumbering at function number 0xC00.
//I leave function numbers in the range 0xA00 to
//0xBFF for weapon functions; this is a total of
//512 unique functions. That is likely much more
//than enough...
#autonumber 0xC00

#include "headers/si_shapes.uc"

#include "headers/constants.uc"	    		//standard constant definitions

#include "headers/constants2.uc"	        //needed these also which include spell visual effects - added Jan 27th 2025 - theGreyWanderer

#include "headers/functions.uc"

#include "headers/si_externals.uc"			//extern declarations for SI functions

#include "headers/si_structs.uc"			//extern declarations for SI functions

#include "headers/global_flags.uc"

#include "headers/u8_npcs.uc"



//ITEMS
#include "items/wand.uc"

#include "utility/convo_start.uc"

#include "utility/time_function.uc"

#include "utility/training_functions.uc"

#include "npcs.uc"	

//COMMON STUFF
#include "common/u8eCommonFunctions.uc"      //u8e common functions - added May 25th 2025 - theGreyWanderer

//SPELL STUFF
#include "spells/tossBottle.uc"

#include "spells/u8eSpellFunctions.uc"      //probably dont need all old spell functions so created new one - added Jan 27th 2025 - theGreyWanderer

#include "spells/theurgyHealingTouch.uc"

#include "spells/theurgyRestoration.uc"

#include "spells/theurgyReveal.uc"

#include "spells/theurgyFadeFromSight.uc"

#include "spells/theurgyDivination.uc"

#include "spells/theurgyAirWalk.uc"

#include "spells/theurgyObjectDebugger.uc"

#include "spells/theurgyFoci.uc" //ensure this is after all theurgy usecode

//ucc -o usecode usecode.uc

//#include "spells/restoration.uc" //theGreyWanderer's Healing Touch focus
//#include "spells/test_focus.uc" //test focus from agentorangeguy

/////CUTSCENES

