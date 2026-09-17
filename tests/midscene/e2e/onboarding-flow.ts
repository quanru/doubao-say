import type { ComputerAgent } from '@midscene/computer';

export const signIn = async (agent: ComputerAgent) => {
  await agent.aiAct(
    'Verify the visible Doubao Say window starts on the Sign in step, says the user is not signed in, and shows an Open Doubao sign-in button. Do not click anything.',
  );
  await agent.aiAct(
    'Click Open Doubao sign-in exactly once, then stop immediately.',
  );
  await new Promise((resolvePromise) => setTimeout(resolvePromise, 1500));
  await agent.aiAct(
    'Verify a Synthetic Doubao sign-in window is visible and explicitly says it is CI-only, makes no network request, and uses no real credentials. Do not click anything.',
  );
  await agent.aiAct(
    'In the Synthetic Doubao sign-in window, click Simulate successful sign-in exactly once, then stop immediately.',
  );
  await agent.aiAct(
    'Verify the synthetic sign-in window closed and the visible Doubao Say window automatically advanced to the Microphone step with a Next button in the fixed top navigation.',
  );
};

export const runOnboardingFlow = async (agent: ComputerAgent) => {
  await signIn(agent);
  await agent.aiAct(
    'Click Next in the Doubao Say fixed top navigation exactly once, then stop immediately. ' +
      'Do not click Next a second time and do not wait for or verify the page transition.',
  );
  await agent.aiAct(
    'Verify the current Doubao Say step is Trigger key. Do not click Previous or Next.',
  );
  await agent.aiAct(
    'Stay on the Trigger key step and do not click Previous or Next. Scroll down inside the light-gray central content panel until the Voice polishing heading and its controls are visible.',
  );
  await agent.aiAct(
    'On the current Trigger key step, click Test endpoint in the visible Voice polishing section and wait for the endpoint result.',
  );
  await agent.aiAct(
    'Verify a visible message says the endpoint works and includes Synthetic endpoint response.',
  );
  await agent.aiAct(
    'Click Next in the fixed top navigation exactly once, then stop immediately. ' +
      'Do not click Next a second time and do not wait for or verify the page transition.',
  );
  await agent.aiAct(
    'Verify the current Doubao Say step is Voice test. Do not click Previous or Next.',
  );
  await agent.aiAct(
    'Verify the Voice test heading and introductory text are visible near the top of the content, proving that navigation reset the previous scroll position.',
  );
  await agent.aiAct(
    'Scroll within the current Voice test content if needed and click Finish setup exactly once. ' +
      'The click is successful when that same button changes to the disabled status ' +
      'Setup completed by the synthetic E2E fixture. When that status appears, stop immediately, ' +
      'do not search for Finish setup again, and do not click Previous or Next.',
  );
  await agent.aiAct(
    'Verify the Finish setup button changed to a disabled visible status saying Setup completed by the synthetic E2E fixture.',
  );
};
