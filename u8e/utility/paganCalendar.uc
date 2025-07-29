var getPaganCalendar() {
    var raw_day_num = UI_game_day(); //get current game day
    var day_num = raw_day_num - 1;  //new var where we force math on current game day
    if (day_num < 0) {
        day_num = 0; //limit in case screw up we dont want negative days
    }
    var hour = UI_game_hour();   //get current hour 0-23
    var minute = UI_game_minute(); //get current minute 0-59

    UI_error_message("getPaganCalendar: raw_day_num=" + raw_day_num + ", day_num=" + day_num + ", hour=" + hour + ", minute=" + minute);

    //calc year and day of year
    var year = day_num / DAYS_PER_YEAR + START_YEAR;
    var day_of_year = day_num % DAYS_PER_YEAR;

    //calc month and day of month
    var month = day_of_year / DAYS_PER_MONTH;
    var day_of_month = day_of_year % DAYS_PER_MONTH;

    //calc week and day of week
    var week = day_of_month / DAYS_PER_WEEK;
    var day_of_week = day_of_month % DAYS_PER_WEEK;

    //calculate time period- each is 4hrs
    var time_period = hour / 4;

    //uc index is 0 so add 1 to everything
    var month_1based = month + 1;
    var day_of_month_1based = day_of_month + 1;
    var week_1based = week + 1;
    var day_of_week_1based = day_of_week + 1;
    var time_period_1based = time_period + 1;

    //use conditionals for names because I didn't want to make a struct and string arrays in usecode seem messed up
    var month_name;
    if (month == STONEMARK) {
        month_name = "Stonemark";
    } else if (month == SKYROCK) {
        month_name = "Skyrock";
    } else if (month == WINDBREAK) {
        month_name = "Windbreak";
    } else if (month == STORMPEAK) {
        month_name = "Stormpeak";
    } else if (month == FIREFALL) {
        month_name = "Firefall";
    } else if (month == DARKFLAME) {
        month_name = "Darkflame";
    } else {
        month_name = "UnknownMonth";
    }

    var day_name;
    if (day_of_week == GUARDAY) {
        day_name = "Guarday";
    } else if (day_of_week == EARTHDAY) {
        day_name = "Earthday";
    } else if (day_of_week == WATERDAY) {
        day_name = "Waterday";
    } else if (day_of_week == AIRDAY) {
        day_name = "Airday";
    } else if (day_of_week == FIREDAY) {
        day_name = "Fireday";
    } else if (day_of_week == BLACKDAY) {
        day_name = "Blackday";
    } else {
        day_name = "UnknownDay";
    }

    var time_name;
    if (time_period == BLOODWATCH) {
        time_name = "Bloodwatch";
    } else if (time_period == FIRSTEBB) {
        time_name = "Firstebb";
    } else if (time_period == DAYTIDE) {
        time_name = "Daytide";
    } else if (time_period == THREEMOONS) {
        time_name = "Threemoons";
    } else if (time_period == LASTEBB) {
        time_name = "Lastebb";
    } else if (time_period == EVENTIDE) {
        time_name = "Eventide";
    } else {
        time_name = "UnknownTime";
    }

    UI_error_message("getPaganCalendar: month=" + month + ", month_name=" + month_name + ", day_of_week=" + day_of_week + ", day_name=" + day_name + ", time_period=" + time_period + ", time_name=" + time_name);

    //return array
    var result = [year, month_1based, day_of_month_1based, week_1based, day_of_week_1based, time_period_1based, month_name, day_name, time_name];
    UI_error_message("getPaganCalendar: result=[" + result[DATE_YEAR] + ", " + result[DATE_MONTH] + ", " + result[DATE_DAY_OF_MONTH] + ", " + result[DATE_WEEK] + ", " + result[DATE_DAY_OF_WEEK] + ", " + result[DATE_TIME_PERIOD] + ", " + result[DATE_MONTH_NAME] + ", " + result[DATE_DAY_NAME] + ", " + result[DATE_TIME_NAME] + "]");
    return result;
}