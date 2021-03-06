import copy
import numpy as np
import time
import gym
import itertools
from matplotlib import pyplot as plt
from torch.distributions.weibull import Weibull
import torch
from Funtions.General import visualize, save_frames_as_gif

# Number of RBF kernels
p1_NUM_RBF = 15
p2_NUM_RBF = 15
v_NUM_RBF = 15

NUM_STATES = p1_NUM_RBF * p2_NUM_RBF * v_NUM_RBF
NUM_ACTIONS = 1
INIT_SIGMA = 0.5
TERM_SIGMA = 0.1

p1_mu = np.linspace(-1, 1, p1_NUM_RBF)
p2_mu = np.linspace(-1, 1, p2_NUM_RBF)
v_mu = np.linspace(-1, 1, v_NUM_RBF)
MUS = np.array(list(itertools.product(p1_mu, p2_mu, v_mu)))


class ActorCritic(object):

    def __init__(self, env, gamma=0.99, sigma=0.1, alpha_value=0.1, alpha_policy=0.1):
        # Upper and lower limits of the state
        self.max_state = env.observation_space.high
        self.min_state = env.observation_space.low

        self.value = np.zeros((NUM_STATES,))
        self.mean_policy = np.zeros((NUM_STATES, NUM_ACTIONS))

        # Discount factor
        self.gamma = gamma

        # Standard deviation of the policy (this will follow epsilon-greedy)
        self.sigma = sigma

        # Standard deviation of the RBF kernel width
        self.rbf_sigma = 0.1

        # Step sizes for the value function and policy
        self.alpha_value = alpha_value
        self.alpha_policy = alpha_policy
        self.env = env

    def _compute_policy_gradient(self, state, mean):
        """ Computes the gradient of the policy function approximator
        Args:
            state (list): list containing the rbf transformed states
            action (float): the action value that's chosen to perform
            advantage (numpy.array): how much better is the state compared to the average value at the given state,
                                     it has the same dimension as the gradient
        Returns:
            [numpy.array]: the gradient of the policy function approximator at the given state, action
        """
        original_state = env.state
        W = Weibull(torch.tensor([np.sqrt(2)], dtype=torch.float32), torch.tensor([2], dtype=torch.float32)).sample()
        a_pos = mean + self.sigma * W.item()
        a_neg = mean - self.sigma * W.item()
        env_pos = gym.make("Pendulum-v0")
        env_neg = gym.make("Pendulum-v0")
        env_pos.reset()
        env_neg.reset()
        env_pos.state[0] = copy.deepcopy(original_state[0])
        env_pos.state[1] = copy.deepcopy(original_state[1])
        env_neg.state[0] = copy.deepcopy(original_state[0])
        env_neg.state[1] = copy.deepcopy(original_state[1])
        next_state_pos, reward_pos, done_pos, _ = env_pos.step([a_pos.item()])
        next_state_neg, reward_neg, done_neg, _ = env_neg.step([a_neg.item()])
        advantage_pos = reward_pos + self.gamma * self._compute_value(self._rbf_transform(next_state_pos), done_pos)
        advantage_neg = reward_neg + self.gamma * self._compute_value(self._rbf_transform(next_state_neg), done_neg)

        grad = (state * (advantage_pos - advantage_neg))
        return grad.T, -(advantage_pos - advantage_neg)

    def _policy_gradient_step(self, grad, I):
        """ Perform one step of the policy (actor) weight update
        Args:
            grad (numpy.array): the gradient of the policy function approximator that's used to update the weights
            I (float): policy weight discounted scaling factor
        """
        self.mean_policy = np.add(self.mean_policy, np.reshape(grad * self.alpha_policy * I, (grad.shape[0], 1)))

    def _update_value(self, state, advantage):
        """ Performs one step of the value (critic) weight update
        Args:
            state (list): list containing the rbf transformed states
            advantage (numpy.array): how much better is the state compared to the average value at the given state,
                                     it has the same dimension as the gradient
        """
        grad_baseline = self.alpha_value * advantage * state
        self.value += grad_baseline

    def _rbf_transform(self, state):
        """ Applies the radial basis function transformation on the raw states to convert to
            discrete states

        Args:
            state (list): raw state from the openai gym environment
        Returns:
            output (numpy.array): the transformed state in the (NUM_STATES, NUM_ACTIONS) dimensions
        """
        output = np.zeros((NUM_STATES, NUM_ACTIONS))

        # Normalize the states between -1 and 1
        state = np.reshape(state, (3,))
        state = np.divide(((state - self.min_state) * 2), (self.max_state - self.min_state)) - 1

        # compute the mean of the states
        state_mu = np.linalg.norm(np.reshape(state, (len(state),)) - MUS, 2, axis=1)

        # compute how far away the original states are from the radial basis function kernel centers
        output = np.array(
            np.exp(- (state_mu) ** 2 / (2 * (self.rbf_sigma ** 2))) / (self.rbf_sigma * np.sqrt(2 * np.pi)))
        return output

    def _compute_mean(self, state):
        """ Predict the mean of the policy function that will be used to generate
            actions later in the pipeline
        Args:
            state (numpy.array): the rbf-converted state
        Returns:
           (float): The mean that will be fed to the gaussian distribution
        """
        return self.mean_policy.T.dot(state)  # linear

    def _compute_value(self, state, done=False):
        """ Computes the value of a given state
        Args:
            state (numpy.array): the rbf-converted state
            done (bool, optional): Whether the current episode is done (last timestep). Defaults to False.
        Returns:
            float: the estimated value for the given state
        """
        # check for terminal state
        if done:
            return 0
        else:
            return self.value.dot(state)

    def act(self, state):
        """ Computes the action given the state by evaluating the gaussian policy
        Args:
            state (numpy.array): the rbf-converted state
        Returns:
            [list]: a list containing the continuous action value
        """
        mean = self._compute_mean(state)  # plug in the state into the function approximator to get mean
        action = np.random.normal(mean, self.sigma)  # the standard deviation is the exp of mean
        return [action], mean

    def update(self, state, action, reward, next_state, done, I, mean):
        """
            1) Computes the value function gradient
            2) Computes the policy gradient
            3) Performs the gradient step for the value and policy functions
            Given the (state, action, reward, next_state) from one step in the environment
        Args:
            state (numpy.array): the rbf-converted state
            action (list): a list containing the continuous action value
            reward (list): a list containing the reward value
            next_state (numpy.array): the rbf-converted next state
            done (bool): whether the episode is done or not
            I (float): policy weight discounted scaling factor
        """
        advantage = reward + self.gamma * self._compute_value(next_state, done) - self._compute_value(state)
        self._update_value(state, advantage)
        grad, _ = self._compute_policy_gradient(state, mean)
        self._policy_gradient_step(grad, I)

    def estimator_variance(self, nr_samples):
        """
        We are interested
        in the variance of the estimators. We compute dL/dmu
        a couple of times without updating the network, then
        the variance is returned
        """
        gradients = []
        environment = gym.make("Pendulum-v0")
        state = environment.reset()
        action, mean = policy.act(policy._rbf_transform(state))
        original_state = env.state
        for i in range(nr_samples):
            environment.state[0] = copy.deepcopy(original_state[0])
            environment.state[1] = copy.deepcopy(original_state[1])

            _, grad = self._compute_policy_gradient(state, mean)
            gradients.append(grad)

        return np.var(gradients)


def plot(i, total_rewards, states, final_plot_i=1000, plot_frequency=100):
    if i > 0 and i % plot_frequency == 0:
        print(f'EP[{i}]: {total_rewards[-1]}')  # raw total rewards for that episode

    if i == final_plot_i:
        fig = plt.figure()
        ax1 = fig.add_subplot(111)
        ax1.set_ylabel('Rewards')
        ax1.set_xlabel('Episodes')
        ax1.set_title('Training (moving avg reward window of 100 episodes)')
        plt.plot(total_rewards)
        plt.show()


def train(env, policy):
    num_episodes = 501
    plot_frequency = 100
    state = env.reset()
    plotting_rewards, plotting_variance = [], []
    for i in range(num_episodes):
        var = policy.estimator_variance(10)
        plotting_variance.append(var)
        I = 1
        done = False
        rewards = []
        states = []
        policy.sigma -= (INIT_SIGMA - TERM_SIGMA) / num_episodes
        state = env.reset()
        while not done:
            state = policy._rbf_transform(state)
            action, mean = policy.act(state)
            next_state, reward, done, _ = env.step(action)
            policy.update(state, action, reward, policy._rbf_transform(next_state), done, I * policy.gamma, mean)
            state = next_state

            # Book keeping
            states.append(state)
            rewards.append(reward)
        if i % 10 == 0:
            print("Epoch ", i, " reward: ", np.sum(rewards))
        plotting_rewards.append(np.sum(rewards))
        moving_rewards = np.convolve(plotting_rewards, np.ones((100,)) / 100, mode='valid')
        plot(i, moving_rewards, states, num_episodes - 1)
    plt.savefig('Results/' + "Moving Average RBF Actor Critic MVD" + '.png')
    return plotting_rewards, plotting_variance


if __name__ == "__main__":
    start_time = time.time()
    env = gym.make('Pendulum-v0')
    env.reset()
    policy = ActorCritic(env, alpha_policy=1e-4, alpha_value=5e-3, sigma=INIT_SIGMA)
    plotting_rewards, plotting_variance = train(env, policy)
    print(f'Training took: {(time.time() - start_time):.2f} seconds')

visualize(plotting_rewards, ylabel="Reward", title="Reward Actor-Critic MVD (RBF)")
visualize(plotting_variance, ylabel="Variance", title="Variance Actor-Critic MVD (RBF)")

state = env.reset()
frames = []
for t in range(1000):
    #Render to frames buffer
    frames.append(env.render(mode="rgb_array"))
    state = policy._rbf_transform(state)
    action, mean = policy.act(state)
    state, reward, done, _ = env.step(action)
    if done:
        break
env.close()
save_frames_as_gif(frames, filename='AC-MVD.gif')