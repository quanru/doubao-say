import type { ComputerAgent } from '@midscene/computer';
import { signIn } from './onboarding-flow';

const openTriggerStep = async (agent: ComputerAgent) => {
  await signIn(agent);
  await agent.aiAct(
    'Click Next in the fixed top navigation exactly once, then stop.',
  );
  await agent.aiAct(
    'Verify the current step is Trigger key and the heading Choose how to start speaking is visible. Do not navigate.',
  );
};

export const cancelAndRetrySignIn = async (agent: ComputerAgent) => {
  await agent.aiAct(
    'Verify the current step is Sign in, the account is not signed in, and both Previous and Next in the fixed top navigation are disabled.',
  );
  await agent.aiAct('Click Open Doubao sign-in exactly once, then stop.');
  await agent.aiAct(
    'Verify the CI-only Synthetic Doubao sign-in window is visible. Close only that synthetic window using its title-bar close button, without clicking Simulate successful sign-in.',
  );
  await agent.aiAct(
    'Verify the synthetic sign-in window is gone, Doubao Say still shows Sign in and Not signed in, Next remains disabled, and Open Doubao sign-in is available.',
  );
  await signIn(agent);
};

export const revisitAccount = async (agent: ComputerAgent) => {
  await signIn(agent);
  await agent.aiAct(
    'Scroll to the bottom of the Microphone central content panel, then click Previous in the fixed top navigation exactly once and stop.',
  );
  await agent.aiAct(
    'Verify the Sign in step shows the heading Your voice, wherever you type near the top of the content without scrolling, and Previous is disabled while Next is enabled.',
  );
  await agent.aiAct(
    'Scroll within the Sign in content if needed. Verify it says Signed in and shows Sign in again / change account. Do not open sign-in.',
  );
  await agent.aiAct(
    'Click Next in the fixed top navigation exactly once, then stop.',
  );
  await agent.aiAct(
    'Verify the Microphone step and its heading Let\'s make sure we can hear you are visible without scrolling, and no synthetic sign-in window is open.',
  );
};

export const requireEnabledTrigger = async (agent: ComputerAgent) => {
  await openTriggerStep(agent);
  await agent.aiAct(
    'In the trigger selection dropdown below Active trigger, select Disabled. Do not change Voice polishing.',
  );
  await agent.aiAct(
    'Click Next in the fixed top navigation exactly once, then stop.',
  );
  await agent.aiAct(
    'Verify the current step is still Trigger key and the message Choose an enabled trigger to continue is visible.',
  );
  await agent.aiAct(
    'In the trigger selection dropdown select F8. Verify Active trigger: F8 and Saved and active: F8 are visible.',
  );
  await agent.aiAct(
    'Click Next in the fixed top navigation exactly once, then stop.',
  );
  await agent.aiAct(
    'Verify the current step is Voice test, the heading Try a sentence. Nothing gets pasted is visible, and Next is disabled.',
  );
  await agent.aiAct(
    'Click Previous exactly once, then stop.',
  );
  await agent.aiAct(
    'Verify the Trigger key step still shows Active trigger: F8 and F8 is selected in the trigger dropdown.',
  );
};

export const togglePolishing = async (agent: ComputerAgent) => {
  await openTriggerStep(agent);
  await agent.aiAct(
    'Scroll inside the central content panel to Voice polishing. Turn off the switch beside that heading.',
  );
  await agent.aiAct(
    'Verify Voice polishing disabled is visible, the switch is off, and the polishing Base URL and Model fields are hidden.',
  );
  await agent.aiAct('Turn on the switch beside Voice polishing.');
  await agent.aiAct(
    'Verify Voice polishing enabled is visible, the switch is on, and the Base URL and Model fields have returned. Scroll within the content if needed and verify Model still contains synthetic-model.',
  );
};

export const retryFailedEndpoint = async (agent: ComputerAgent) => {
  await openTriggerStep(agent);
  await agent.aiAct(
    'Scroll inside the central content panel to Voice polishing. Replace the Model field with synthetic-failing-model, then click Test endpoint exactly once, scrolling within the panel if needed.',
  );
  await agent.aiAct(
    'Verify the visible endpoint feedback says Endpoint test failed: Synthetic endpoint unavailable, and the enabled retry button says Test failed — try again.',
  );
  await agent.aiAct(
    'Scroll within the Voice polishing content to the Model field and replace its value with synthetic-model. Scroll back to the Test failed — try again button and click it exactly once.',
  );
  await agent.aiAct(
    'Verify the endpoint result says Endpoint works: Synthetic endpoint response, the enabled button says Endpoint works, and the previous Synthetic endpoint unavailable error is no longer visible.',
  );
};
