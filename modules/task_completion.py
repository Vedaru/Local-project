"""
Task Completion Recognition Module

This module helps the agent understand task completion based on process reasoning,
NOT keyword matching. The agent should understand what it's trying to accomplish
and recognize when the goal has been achieved.
"""

from typing import List, Dict, Any
from enum import Enum


class TaskCompletionHelper:
    """
    Helps Agent understand task completion through process awareness,
    not keyword triggers.
    
    Key principle: Agent should understand:
    1. What am I trying to accomplish? (Core objective)
    2. What steps have I taken? (Progress tracking)
    3. Have I achieved the goal? (Completion detection)
    
    Do NOT rely on keyword matching to determine task type or completion.
    """
    
    @staticmethod
    def get_completion_guidance() -> str:
        """
        Get general guidance for recognizing task completion through process understanding.
        This is NOT task-specific - applies to ALL tasks equally.
        """
        return """\n
【Task Completion Through Process Understanding】

You should recognize task completion by understanding the process, NOT by matching keywords.

For ANY task you receive:
1. FIRST: Understand what the core objective is
   - What does the user want me to accomplish?
   - What is the final state they expect?

2. DURING: Track your progress toward that objective
   - What steps am I taking?
   - Am I getting closer to the goal?
   - Have I hit any blockers?

3. COMPLETION: Stop when the objective is achieved
   - Have I done what was asked?
   - Is the final state reached?
   - Would continuing to interact add value or just waste time?

【Examples of Task Completion】
These apply to ANY task, regardless of what words are in the task description:

✅ SEARCH/FIND: When you have extracted the requested information
   "Search for X" → Found X → Present it → DONE
   Do NOT continue searching or scrolling

✅ NAVIGATE/ACCESS: When you have successfully reached the target
   "Visit website Y" → Reached Y → DONE  
   Do NOT explore unrelated parts

✅ ACTION/EXECUTION: When the action is complete
   "Click X" → Clicked → Check result → DONE
   Do NOT click random other elements

✅ CONTENT EXTRACTION: When you have the information needed
   "Extract Z from page" → Found Z → Extracted → DONE
   Do NOT continue scrolling for more

✅ MEDIA/PLAYBACK: When content is playing/working
   "Play video" → Video playing → DONE
   Do NOT click other elements on the page

✅ CREATION/MODIFICATION: When the artifact exists and is correct
   "Create file X" → File created → DONE
   Do NOT keep modifying unnecessarily

【Critical Anti-Patterns to AVOID】
These apply to ALL tasks - do NOT do these things:

❌ Random clicking after finding information
❌ Unnecessary scrolling "to see what else is there"  
❌ Visiting unrelated pages or links
❌ Testing ideas that weren't part of the task
❌ Continuing after the goal has been reached

【How to Tell You're Done】
Stop immediately when:
- The information/action/object requested has been achieved
- Further interaction would NOT accomplish more of the task objective
- You would only be exploring, testing, or satisfying curiosity

Do NOT wait for some special signal - use your understanding of the task to decide.
"""
    
    @staticmethod
    def get_process_awareness_guidance() -> str:
        """
        Guidance for understanding task flow through reasoning, not keywords.
        """
        return """\n
【Process-Based Task Understanding】

For each task, reason about it like this:

1. PARSE OBJECTIVE (Don't match keywords - understand intent)
   - What is the user asking me to do?
   - What is the end goal?
   - What would "success" look like?
   
2. IDENTIFY STEPS (Understand the process flow)
   - What tools do I need? (browser, code, search, file operations)
   - What is the natural sequence?
   - When would this process be complete?

3. RECOGNIZE COMPLETION (Understand when to stop)
   - Have I taken the necessary steps?
   - Have I achieved what was requested?
   - Is further action necessary OR am I just exploring?

4. EXECUTE DECISION (Call terminate at the right time)
   - If complete: call terminate immediately
   - If blocked: diagnose and fix the blocker
   - If uncertain: ask yourself "does the user need more than this?"

【Examples by Understanding, Not Keywords】

NO: "If the task mentions 'video' OR 'bilibili' → apply special rules"
YES: "I need to navigate to a video and play it
      → I go to the URL → I verify playback → I stop"

NO: "If task contains 'search' → find info → stop"  
YES: "User wants information about X
      → I search → I find X → I present it → I stop"

NO: "If task has 'create' → make file → stop"
YES: "User needs file with specific content
      → I create it → I verify correctness → I stop"

The pattern is: Understand → Execute → Verify → Complete

【When You're Uncertain】

Ask yourself:
- "What did the user ask for?" (re-read the task)
- "Have I provided that?" (verify against the task)
- "Would the user expect more?" (use judgment)
- "Should I call terminate now?" (yes if the above are satisfied)

Remember: By understanding the task process, you'll naturally know when to stop.
Do NOT try to pattern-match against keywords or pre-set rules.
"""
