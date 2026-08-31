//necromancyWithstandDeath.uc

var findWithstandDeathAvatarBody()
{
    var bodyShapes = [400, 402, 414, 507, 762, 778, 892];
    var shape;

    for (shape in bodyShapes)
    {
        var nearbyBodies = AVATAR->find_nearby(shape, 25, MASK_NONE);
        var body;

        for (body in nearbyBodies)
        {
            if (body->get_body_npc() == AVATAR)
            {
                return body;
            }
        }
    }

    return 0;
}

void withstandDeathWatch object#() ()
{
    if (!gflags[WITHSTAND_DEATH_ACTIVE])
    {
        return;
    }

    if (UI_get_item_flag(AVATAR, DEAD))
    {
        var avatarBody = findWithstandDeathAvatarBody();
        if (avatarBody && avatarBody->resurrect())
        {
            gflags[WITHSTAND_DEATH_ACTIVE] = false;
            restoreNpcToFullHealth(AVATAR);
            AVATAR->item_say("@Death shall not claim me yet!@");
            return;
        }
    }

    script AVATAR after 1 ticks {
        nohalt;
        call withstandDeathWatch;
    }
}

void necromancyWithstandDeath object#() () {
    var talisman = item;
    var caster = getOuterContainer(talisman);
    if (!caster || !caster->is_npc()) {
        UI_error_message("No valid caster found for necromancy talisman");
        return;
    }

    if (caster != AVATAR)
    {
        caster->item_say("@Only I may bear this ward.@");
        return;
    }

    if (gflags[WITHSTAND_DEATH_ACTIVE])
    {
        caster->item_say("@The ward already waits upon me.@");
        return;
    }

    if (!spendMagicMana(caster, 4)) {
        return;
    }

    caster->item_say("@Vas An Corp@");

    script caster {
        nohalt;
        actor frame CAST_1;
        actor frame CAST_2;
        sfx 67;
        wait 4;
        actor frame STAND;
    }

    gflags[WITHSTAND_DEATH_ACTIVE] = true;

    script AVATAR after 1 ticks {
        nohalt;
        call withstandDeathWatch;
    }

    talisman->remove_item();
}