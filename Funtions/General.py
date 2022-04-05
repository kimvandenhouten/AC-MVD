from matplotlib import animation
import matplotlib.pyplot as plt

"""
Ensure you have imagemagick installed with 
sudo apt-get install imagemagick
Open file in CLI with:
xgd-open <filelname>
"""


def save_frames_as_gif(frames, path='./Animations/', filename='gym_animation.gif'):
    plt.figure(figsize=(frames[0].shape[1] / 72.0, frames[0].shape[0] / 72.0), dpi=72)
    patch = plt.imshow(frames[0])
    plt.axis('off')

    def animate(i):
        patch.set_data(frames[i])

    anim = animation.FuncAnimation(plt.gcf(), animate, frames=len(frames), interval=50)
    anim.save(path + filename, writer='imagemagick', fps=60)


def visualize(rewards, ylabel, title):
    plt.figure(figsize=(15, 5))
    plt.ylabel(ylabel)
    plt.xlabel(ylabel)
    plt.title(title)
    x = list(range(1, 1 + len(rewards)))
    plt.plot(x, rewards)
    plt.savefig('Results/' + title + '.png')
