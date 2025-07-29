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

#include "headers/functions.uc"

#include "headers/si_externals.uc"			//extern declarations for SI functions

#include "headers/u8e_structs.uc"			//extern declarations for SI functions

#include "headers/global_flags.uc"

#include "headers/u8e_Shapes.uc"

#include "headers/u8e_gflags.uc"

#include "headers/u8_npcs.uc"

#include "headers/u8e_sprites.uc"

#include "headers/u8e_constants.uc"

#include "headers/u8e_functions.uc"



//ITEMS
#include "items/wand.uc"

#include "utility/convo_start.uc"

#include "utility/time_function.uc"

#include "utility/paganCalendar.uc"

//#include "utility/smoke.uc" //testing

#include "utility/training_functions.uc"

#include "npcs.uc"	

//SPELL STUFF
#include "spells/theurgyHealingTouch.uc"

#include "spells/theurgyRestoration.uc"

#include "spells/theurgyReveal.uc"

#include "spells/theurgyFadeFromSight.uc"

#include "spells/theurgyDivination.uc"

#include "spells/theurgyAerialServant.uc"

#include "spells/theurgyAirWalk.uc"

#include "spells/theurgyObjectDebugger.uc"

#include "spells/theurgyFoci.uc" //ensure this is after all theurgy includes

#include "spells/necromancyKeyCaretaker.uc"

//ucc -o usecode usecode.uc

//#include "spells/restoration.uc" //theGreyWanderer's Healing Touch focus
//#include "spells/test_focus.uc" //test focus from agentorangeguy

/////CUTSCENES

