"""
DQN Agent with Prioritized Experience Replay.

This file implements the DQN agent with Prioritized Experience Replay for 
playing Atari Ice Hockey. It handles interaction with the environment,
experience storage, and network training.

使用優先經驗回放的 DQN 智能體。

該文件實現了使用優先經驗回放的 DQN 智能體，用於玩 Atari 冰球遊戲。
它負責與環境交互、經驗存儲和網絡訓練。

Pseudocode for DQN with PER:
1. Initialize primary Q-network Q with random weights θ
2. Initialize target Q-network Q' with weights θ' = θ
3. Initialize Prioritized Experience Replay memory D
4. For each episode:
   a. Initialize state s_1
   b. For each time step t:
      i. Select action a_t using ε-greedy policy based on Q(s_t; θ)
      ii. Execute action a_t, observe reward r_t and next state s_{t+1}
      iii. Store transition (s_t, a_t, r_t, s_{t+1}, done) in D with max priority
      iv. If enough samples in D:
         - Sample batch of transitions (s_j, a_j, r_j, s_{j+1}, done_j) with priority
         - Calculate importance sampling weights w_j
         - Calculate TD-error δ_j = r_j + γ·max_a Q'(s_{j+1}, a; θ') - Q(s_j, a_j; θ)
         - Update priorities in D using |δ_j|
         - Calculate loss L = 1/B · Σ w_j · (δ_j)²
         - Perform gradient descent step on L with respect to θ
      v. Every C steps, update target network θ' ← θ
"""

import numpy as np
import torch
import torch.nn.functional as F
import torch.optim as optim
import random
import os
from config import (
    LEARNING_RATE, GAMMA, BATCH_SIZE, EPSILON_START, EPSILON_END, 
    EPSILON_DECAY, TARGET_UPDATE_FREQUENCY, GRAD_CLIP_NORM, USE_PER, EPSILON_PER,
    ACTION_SPACE_SIZE
)
from src.agent.q_network import DQN
from src.memory.per_memory import PrioritizedReplayMemory


class DQNAgent:
    """
    DQN Agent with support for Prioritized Experience Replay.
    
    This agent uses Deep Q-Networks with optional Prioritized Experience Replay
    to learn how to play Atari Ice Hockey.
    
    具有優先經驗回放支持的 DQN 智能體。
    
    該智能體使用深度 Q 網絡（可選優先經驗回放）來學習如何玩 Atari 冰球遊戲。
    """
    
    def __init__(self, device, memory_capacity=100000, use_per=USE_PER):
        """
        Initialize the DQN agent.
        
        Args:
            device (torch.device): Device to run the networks on (CPU/GPU/M系列晶片)
            memory_capacity (int): Capacity of the replay memory
            use_per (bool): Whether to use Prioritized Experience Replay
            
        初始化 DQN 智能體。
        
        參數：
            device (torch.device)：運行網絡的設備（CPU/GPU/M系列晶片）
            memory_capacity (int)：回放記憶體的容量
            use_per (bool)：是否使用優先經驗回放
        """
        # Set the device
        self.device = device
        print(f"Using device: {device}")
        
        # Initialize Q-Networks
        self.policy_net = DQN().to(device)  # Primary network for action selection
        self.target_net = DQN().to(device)  # Target network for stable learning
        self.target_net.load_state_dict(self.policy_net.state_dict())  # Copy initial weights
        self.target_net.eval()  # Target network is only used for inference
        
        # Initialize optimizer
        self.optimizer = optim.Adam(self.policy_net.parameters(), lr=LEARNING_RATE)
        
        # Replay memory
        self.use_per = use_per
        if use_per:
            print("Using Prioritized Experience Replay")
            self.memory = PrioritizedReplayMemory(capacity=memory_capacity)
        else:
            # For future compatibility, could add a standard uniform replay memory here
            print("Using Prioritized Experience Replay (PER with alpha=0 behaves like uniform replay)")
            self.memory = PrioritizedReplayMemory(capacity=memory_capacity)
        
        # Initialize step counter (used for epsilon decay and target network updates)
        self.steps_done = 0
        
        # Training info
        self.loss = 0
    
    def select_action(self, state, evaluate=False):
        """
        Select an action using epsilon-greedy policy.
        
        Args:
            state (numpy.ndarray): Current state observation
            evaluate (bool): Whether to use greedy policy (for evaluation)
            
        Returns:
            int: Selected action
            
        使用 epsilon-greedy 策略選擇動作。
        
        參數：
            state (numpy.ndarray)：當前狀態觀察
            evaluate (bool)：是否使用貪婪策略（用於評估）
            
        返回：
            int：選擇的動作
        """
        # Calculate current epsilon
        if evaluate:
            # Use greedy policy for evaluation
            epsilon = 0
        else:
            # Decay epsilon over time
            epsilon = EPSILON_END + (EPSILON_START - EPSILON_END) * \
                      np.exp(-1. * self.steps_done / EPSILON_DECAY)
            
            # Increment step counter
            self.steps_done += 1
        
        # Convert state to PyTorch tensor for network forward pass
        state_tensor = torch.FloatTensor(state).unsqueeze(0).to(self.device)
        
        # Epsilon-greedy action selection
        if random.random() > epsilon:
            # Exploit: select best action
            with torch.no_grad():
                # Forward pass through policy network
                q_values = self.policy_net(state_tensor)
                
                # Select action with highest Q-value
                action = q_values.max(1)[1].item()
        else:
            # Explore: select random action
            action = random.randrange(ACTION_SPACE_SIZE)
        
        return action
    
    def store_transition(self, state, action, reward, next_state, done):
        """
        Store a transition in the replay memory.
        
        Args:
            state (numpy.ndarray): Current state
            action (int): Action taken
            reward (float): Reward received
            next_state (numpy.ndarray): Next state
            done (bool): Whether the episode ended
            
        將轉換存儲在回放記憶體中。
        
        參數：
            state (numpy.ndarray)：當前狀態
            action (int)：採取的動作
            reward (float)：獲得的獎勵
            next_state (numpy.ndarray)：下一個狀態
            done (bool)：回合是否結束
        """
        # Add the transition to memory
        self.memory.add(state, action, reward, next_state, done)
    
    def update_target_network(self):
        """
        Update the target network by copying weights from the policy network.
        
        通過從策略網絡複製權重來更新目標網絡。
        """
        self.target_net.load_state_dict(self.policy_net.state_dict())
    
    def optimize_model(self):
        """
        Perform a single optimization step.
        
        Returns:
            float: The loss value for this batch
            
        執行單個優化步驟。
        
        返回：
            float：此批次的損失值
        """
        # Check if memory has enough samples
        if len(self.memory) < BATCH_SIZE:
            return 0
        
        # Sample a batch of transitions with priorities and importance weights
        # If using standard memory, weights would be all 1s
        batch, indices, weights = self.memory.sample(BATCH_SIZE)
        
        # Unpack the batch
        states, actions, rewards, next_states, dones = batch
        
        # Compute current Q values: Q(s, a)
        # We want to get Q values only for the actions that were taken
        current_q_values = self.policy_net(states).gather(1, actions.unsqueeze(1))
        
        # Compute max Q values for next states using the target network: max_a Q'(s', a)
        with torch.no_grad():
            next_q_values = self.target_net(next_states).max(1)[0]
        
        # Compute the expected (or target) Q values
        # If done, target = reward, else target = reward + gamma * max_a Q'(s', a)
        expected_q_values = rewards + GAMMA * next_q_values * (1 - dones)
        
        # Reshape for loss calculation
        expected_q_values = expected_q_values.unsqueeze(1)
        
        # Calculate TD errors for updating priorities in PER
        td_errors = (expected_q_values - current_q_values).detach().cpu().numpy()
        
        # If using PER, update priorities based on TD errors
        if self.use_per:
            # Update transition priorities
            self.memory.update_priorities(indices, np.abs(td_errors.flatten()) + EPSILON_PER)
        
        # Calculate the weighted loss
        # If using standard memory, weights would be all 1s
        loss = (weights.unsqueeze(1) * F.smooth_l1_loss(
            current_q_values, expected_q_values, reduction='none'
        )).mean()
        
        # Optimize the model
        self.optimizer.zero_grad()
        loss.backward()
        
        # Clip gradients to prevent exploding gradients
        torch.nn.utils.clip_grad_norm_(self.policy_net.parameters(), GRAD_CLIP_NORM)
        
        # Apply gradients
        self.optimizer.step()
        
        # Store the loss for monitoring
        self.loss = loss.item()
        
        # Return the loss value
        return loss.item()
    
    def should_update_target_network(self):
        """
        Check if it's time to update the target network.
        
        Returns:
            bool: True if it's time to update the target network
        """
        # Fix: Ensure this returns True exactly when steps_done is a multiple of TARGET_UPDATE_FREQUENCY
        return self.steps_done > 0 and self.steps_done % TARGET_UPDATE_FREQUENCY == 0
    
    def save(self, path, additional_data=None):
        """
        Save the agent's state (policy network, target network, optimizer) and optional training data.
        
        Args:
            path (str): Path to save the model
            additional_data (dict, optional): Additional training statistics to save
            
        保存智能體的狀態（策略網絡、目標網絡、優化器）和可選的訓練數據。
        
        參數：
            path (str)：保存模型的路徑
            additional_data (dict, optional)：要保存的額外訓練統計數據
        """
        # Create base data dictionary with model states
        save_data = {
            'policy_net_state_dict': self.policy_net.state_dict(),
            'target_net_state_dict': self.target_net.state_dict(),
            'optimizer_state_dict': self.optimizer.state_dict(),
            'steps_done': self.steps_done
        }
        
        # Add any additional data if provided
        if additional_data is not None and isinstance(additional_data, dict):
            save_data.update(additional_data)
            
        # Save with guaranteed directory creation
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        torch.save(save_data, path)
    
    def load(self, path):
        """
        Load the agent's state from a saved file.
        
        Args:
            path (str): Path to the saved model
            
        Returns:
            dict: Training statistics if available
        """
        checkpoint = torch.load(path, map_location=self.device)
        self.policy_net.load_state_dict(checkpoint['policy_net_state_dict'])
        self.target_net.load_state_dict(checkpoint['target_net_state_dict'])
        self.optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
        self.steps_done = checkpoint['steps_done']
        
        # Return the full checkpoint which may contain additional training stats
        return checkpoint