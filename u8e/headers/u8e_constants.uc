const int START_YEAR = 861;
const int EXTRA_DAYS_PER_MONTH = 3;

enum pagan_time {
    DAYS_PER_WEEK = 6,
    WEEKS_PER_MONTH = 7,
    DAYS_PER_MONTH = 45,
    MONTHS_PER_YEAR = 6,
    DAYS_PER_YEAR = 270
};

enum pagan_time_periods {
    BLOODWATCH = 0,  // 00:00–04:00
    FIRSTEBB = 1,    // 04:00–08:00
    DAYTIDE = 2,     // 08:00–12:00
    THREEMOONS = 3,  // 12:00–16:00
    LASTEBB = 4,     // 16:00–20:00
    EVENTIDE = 5     // 20:00–00:00
};

enum pagan_days {
    GUARDAY = 0,
    EARTHDAY = 1,
    WATERDAY = 2,
    AIRDAY = 3,
    FIREDAY = 4,
    BLACKDAY = 5
};

enum pagan_weeks { // Pagan weeks do not have Names.
    WEEK1 = 0,   // Week 1
    WEEK2 = 1,   // Week 2
    WEEK3 = 2,   // Week 3
    WEEK4 = 3,   // Week 4
    WEEK5 = 4,   // Week 5
    WEEK6 = 5,   // Week 6
    WEEK7 = 6    // Week 7
};

enum pagan_months {
    STONEMARK = 0,
    SKYROCK = 1,
    WINDBREAK = 2,
    STORMPEAK = 3,
    FIREFALL = 4,
    DARKFLAME = 5
};

//array indices for getPaganCalendar return array
const int DATE_YEAR = 1;
const int DATE_MONTH = 2;
const int DATE_DAY_OF_MONTH = 3;
const int DATE_WEEK = 4;
const int DATE_DAY_OF_WEEK = 5;
const int DATE_TIME_PERIOD = 6;
const int DATE_MONTH_NAME = 7;
const int DATE_DAY_NAME = 8;
const int DATE_TIME_NAME = 9;

//u8e necromancer talisman frames
const int FRAME_NECROMANCY_OPENGROUND	=  0;
const int FRAME_NECROMANCY_CALLQUAKE	=  1;
const int FRAME_NECROMANCY_ROCKFLESH	=  2;
const int FRAME_NECROMANCY_CREATEGOLEM =  3;
const int FRAME_NECROMANCY_DEATHSPEAK	=  4;
const int FRAME_NECROMANCY_MASKDEATH	=  5;
const int FRAME_NECROMANCY_SUMMONDEAD	=  6;
const int FRAME_NECROMANCY_WITHSTANDDEATH	=  7;
const int FRAME_NECROMANCY_GRANTPEACE	=  8;


//u8e reagent frames
const int FRAME_NECROMANCY_DIRT	=  9;
const int FRAME_NECROMANCY_BLACKMOOR	=  10;
const int FRAME_NECROMANCY_EXECUTIONHOOD	=  12;
const int FRAME_NECROMANCY_BONES	=  13;
const int FRAME_NECROMANCY_WOOD	=  14;
const int FRAME_NECROMANCY_BLOOD	=  15;
const int FRAME_NECROMANCY_DEADMANELBOW	=  16;


enum faces
{
   AERIAL_SERVANT_FACE        = 237 //placeholder
};

enum npc_frames
{
    RAISE_2H	= 30	//both arms raised above head

};